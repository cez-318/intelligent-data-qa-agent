from pathlib import Path
from pydantic import ValidationError
import sqlglot
from sqlglot import exp
from improved.compiler import SemanticCompiler, Decision, PlanRejected
from improved.model_calls import invoke_json
from improved.intent_contract import missing_entity_constraints
from improved.analysis_queries import build_analysis_queries


async def generate_sql(state, runtime):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "理解问题并生成查询计划", "status": "running"})
    compiler = SemanticCompiler()
    instructions = (Path(__file__).resolve().parents[3] / "prompts" / "plan_query.txt").read_text(encoding="utf-8")
    payload = {"query": state["query"], "tables": state["table_infos"], "metrics": state["metric_infos"],
               "date_info": state["date_info"], "db_info": state["db_info"], "registry": compiler.rules}
    if state.get("error"):
        payload["previous_validation_error"] = state["error"]
        payload["previous_plan"] = state.get("query_plan")
        payload["previous_sql"] = state.get("sql")
    raw = await invoke_json("plan_query", payload, instructions)
    try:
        decision = Decision.model_validate(raw)
        if decision.mode == "clarify":
            return {"clarification": decision.message or "请补充指标口径、统计时间或筛选条件。"}
        if decision.mode == "metric":
            if decision.plan is None:
                raise PlanRejected("缺少结构化查询计划")
            missing = missing_entity_constraints(state['query'], decision.plan, compiler.rules.get('entity_constraints', []))
            if missing:
                repaired = await invoke_json('repair_intent', {**payload, 'proposed_plan':decision.plan.model_dump(),
                                             'missing_entity_constraints':missing}, instructions + '\n已检测到明确实体条件遗漏。重新生成完整决策，不能省略这些实体；若不能确定条件含义则clarify。')
                decision = Decision.model_validate(repaired)
                if decision.mode == 'clarify':
                    return {'clarification': decision.message or '请确认实体和两期筛选范围。'}
                if decision.mode != 'metric' or decision.plan is None or missing_entity_constraints(state['query'], decision.plan, compiler.rules.get('entity_constraints', [])):
                    raise PlanRejected('实体筛选约束仍未覆盖，停止执行')
            analysis_queries = build_analysis_queries(decision.plan, compiler) if decision.plan.analysis else []
            compiled = compiler.compile(decision.plan)
            baseline = compiler.compile(decision.plan, comparison=True) if decision.plan.comparison_filters is not None else None
            result = {"sql": compiled.sql, "sql_params": compiled.params, "query_plan": decision.plan.model_dump(),
                      "semantic_definitions": compiled.definitions, "semantic_version": compiled.version,
                      "comparison_sql": baseline.sql if baseline else None,
                      "comparison_params": baseline.params if baseline else {}, "clarification": None}
            result['analysis_queries'] = analysis_queries
        else:
            if compiler.rules.get("required_filters"):
                raise PlanRejected("存在强制业务筛选条件，请使用已注册指标查询")
            tree = sqlglot.parse_one(decision.sql or "", read="mysql")
            if any(tree.find_all(exp.AggFunc)):
                raise PlanRejected("聚合查询需先选择已注册指标口径")
            result = {"sql": decision.sql, "sql_params": {}, "query_plan": None,
                      "semantic_definitions": {}, "semantic_version": None,
                      "comparison_sql": None, "comparison_params": {}, "clarification": None}
            result['analysis_queries'] = []
    except (PlanRejected, ValidationError, sqlglot.errors.SqlglotError):
        return {"clarification": "无法按已批准的指标和字段生成查询。请明确指标、时间及筛选条件，或由维护者补充指标配置。"}
    writer({"type": "progress", "step": "理解问题并生成查询计划", "status": "success"})
    return result


def generation_route(state):
    return "clarify_query" if state.get("clarification") else "validate_sql"


async def clarify_query(state, runtime):
    runtime.stream_writer({"type": "progress", "step": "理解问题并生成查询计划", "status": "success"})
    runtime.stream_writer({"type": "clarification", "message": state["clarification"]})
    return {}
