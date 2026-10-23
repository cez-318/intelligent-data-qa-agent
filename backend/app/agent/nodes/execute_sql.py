import time
from improved.result_analysis import compare_rows
from improved.analysis_execution import execute_decomposition
from improved.decomposition import AnalysisRejected


async def execute_sql(state, runtime):
    writer = runtime.stream_writer
    repository = runtime.context["dw_mysql_repository"]
    writer({"type": "progress", "step": "执行已校验查询", "status": "running"})
    if state.get('analysis_queries'):
        try:
            output = await execute_decomposition(state, repository)
        except AnalysisRejected:
            writer({'type':'progress','step':'执行已校验查询','status':'error'})
            writer({'type':'clarification','message':'贡献分解未通过完整性或口径核对，已停止输出解释。请确认互斥分组、两期范围和有效订单数。'})
            return {}
        writer({'type':'progress','step':'执行已校验查询','status':'success'})
        writer(output)
        return {'result_rows':output['data']}
    started = time.perf_counter()
    rows = await repository.execute_sql(state["sql"], state.get("sql_params", {}))
    baseline = None
    if state.get("comparison_sql"):
        baseline = await repository.execute_sql(state["comparison_sql"], state.get("comparison_params", {}))
    # SQL qualification may normalize aliases; restore registered public names.
    plan = state.get("query_plan")
    names = {name.casefold(): name for name in plan["metrics"]} if plan else {}
    def public_rows(items):
        return [{names.get(key.casefold(), key): value for key, value in row.items()
                 if key.casefold() != "__sample_rows"} for row in items]
    rows = public_rows(rows)
    if baseline is not None:
        baseline = public_rows(baseline)
    analysis = compare_rows(rows, baseline, plan["dimensions"], plan["metrics"]) if baseline is not None and plan else None
    evidence = {"mode": "llm_rag", "sql": state["sql"], "parameters": state.get("sql_params", {}),
                "definitions": state.get("semantic_definitions", {}), "semantic_version": state.get("semantic_version"),
                "query_plan": plan, "row_limit": repository.guard.max_rows,
                "possibly_truncated": len(rows) >= repository.guard.max_rows or (plan is not None and len(rows) >= plan["limit"])}
    summary = f"查询完成，返回 {len(rows)} 行。" if rows else "没有符合条件的数据，不解释为零。"
    if analysis is not None:
        summary += " 对比仅基于返回分组，缺失分组不视为零，不代表因果解释。"
    writer({"type": "progress", "step": "执行已校验查询", "status": "success"})
    writer({"type": "result", "data": rows, "comparison_data": baseline, "analysis": analysis,
            "summary": summary, "evidence": evidence, "execution_ms": round((time.perf_counter()-started)*1000, 2)})
    return {"result_rows": rows}
