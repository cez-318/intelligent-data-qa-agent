"""Compile LLM-produced structured intent using administrator-owned business rules.

No question regexes, fixed answers, or hard-coded time periods live here.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import re
import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr
from improved.guard import SQLGuard
from improved.profiles import active_profile

CONF = Path(__file__).resolve().parents[1] / "conf"
Scalar = StrictStr | StrictInt | StrictFloat


class PlanRejected(ValueError):
    pass


class Filter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "between", "is_null", "not_null"]
    value: Scalar | list[Scalar] | None = None


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    analysis: Literal["segments", "volume_value"] | None = None
    metrics: list[str] = Field(min_length=1, max_length=5)
    dimensions: list[str] = Field(default_factory=list, max_length=5)
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    comparison_filters: list[Filter] | None = Field(default=None, max_length=20)
    order_by: str | None = None
    descending: bool = True
    limit: int = Field(default=100, ge=1, le=200)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["metric", "sql", "clarify"]
    plan: QueryPlan | None = None
    sql: str | None = Field(default=None, max_length=20000)
    message: str = Field(default="", max_length=500)


@dataclass
class CompiledQuery:
    sql: str
    params: dict
    definitions: dict
    version: str


class SemanticCompiler:
    def __init__(self, conf=None):
        self.conf = Path(conf) if conf is not None else active_profile().conf
        self.policy = yaml.safe_load((self.conf / "query_policy.yaml").read_text(encoding="utf-8"))
        self.rules = yaml.safe_load((self.conf / "rag_semantics.yaml").read_text(encoding="utf-8"))
        metadata = yaml.safe_load((self.conf / "meta_config.yaml").read_text(encoding="utf-8"))
        self.roles = {f"{t['name']}.{c['name']}": c["role"] for t in metadata["tables"] for c in t["columns"]}

    def field(self, name, *, dimension=False):
        if not re.fullmatch(r"[A-Za-z_]\w*\.[A-Za-z_]\w*", name):
            raise PlanRejected("字段格式不合法")
        table, column = name.split(".")
        if column not in self.policy["tables"].get(table, []):
            raise PlanRejected("字段不在授权范围")
        if dimension and self.roles.get(name) not in {"dimension", "primary_key", "foreign_key"}:
            raise PlanRejected("该字段不是已注册维度")
        return table, column

    def compile(self, plan: QueryPlan, *, comparison=False) -> CompiledQuery:
        metrics = list(dict.fromkeys(plan.metrics))
        dimensions = list(dict.fromkeys(plan.dimensions))
        if any(name not in self.rules["metrics"] for name in metrics):
            raise PlanRejected("指标未注册，请先确认业务口径")
        roots = {self.rules["metrics"][name]["base_table"] for name in metrics}
        if len(roots) != 1:
            raise PlanRejected("跨事实表指标需要先配置统一粒度")
        root = roots.pop()
        if self.rules.get("joins_are_many_to_one") is not True:
            raise PlanRejected("关联基数尚未确认")
        required = {root}
        expressions, definitions = [], {}
        for name in metrics:
            if not re.fullmatch(r"[A-Za-z_]\w*", name):
                raise PlanRejected("指标标识不合法")
            rule = self.rules["metrics"][name]
            expressions.append(f"{rule['expression']} AS {name}")
            definitions[name] = rule["definition"]
            for column in rule["required_columns"]:
                required.add(self.field(column)[0])
        for name in dimensions:
            required.add(self.field(name, dimension=True)[0])
            expressions.append(f"{name} AS {name.replace('.', '__')}")
        filters = plan.comparison_filters if comparison else plan.filters
        if filters is None:
            raise PlanRejected("缺少对比期条件")
        # Required filters are server-owned and cannot be removed by an LLM plan.
        filters = [Filter(**item) for item in self.rules.get("required_filters", [])] + list(filters)
        params, predicates = {}, []
        for index, item in enumerate(filters):
            required.add(self.field(item.field)[0])
            key = f"p{index}"
            if item.op in {"is_null", "not_null"}:
                if item.value is not None:
                    raise PlanRejected("空值条件不接受额外取值")
                predicates.append(f"{item.field} IS {'NOT ' if item.op == 'not_null' else ''}NULL")
            elif item.op in {"in", "between"}:
                if not isinstance(item.value, list) or not 1 <= len(item.value) <= 50:
                    raise PlanRejected("集合条件必须包含1至50个值")
                if item.op == "between" and len(item.value) != 2:
                    raise PlanRejected("区间必须有两个边界")
                slots = []
                for offset, value in enumerate(item.value):
                    params[f"{key}_{offset}"] = value
                    slots.append(f":{key}_{offset}")
                predicates.append(f"{item.field} IN ({', '.join(slots)})" if item.op == "in" else f"{item.field} BETWEEN {slots[0]} AND {slots[1]}")
            else:
                if item.value is None or isinstance(item.value, list):
                    raise PlanRejected("比较条件需要单个值")
                operator = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[item.op]
                predicates.append(f"{item.field} {operator} :{key}")
                params[key] = item.value
        connected, joins = {root}, []
        pending = set(required) - connected
        while pending:
            progress = False
            for left, lcol, right, rcol in self.rules["relationships"]:
                if left in connected and right in pending:
                    self.field(f"{left}.{lcol}")
                    self.field(f"{right}.{rcol}")
                    joins.append(f"LEFT JOIN {right} ON {left}.{lcol} = {right}.{rcol}")
                    connected.add(right)
                    pending.remove(right)
                    progress = True
            if not progress:
                raise PlanRejected("所选维度缺少已批准的多对一关联")
        expressions.append("COUNT(*) AS __sample_rows")
        sql = f"SELECT {', '.join(expressions)} FROM {root} " + " ".join(joins)
        if predicates:
            sql += " WHERE " + " AND ".join(predicates)
        if dimensions:
            sql += " GROUP BY " + ", ".join(dimensions)
        sql += " HAVING COUNT(*) > 0"
        if plan.order_by:
            if plan.order_by not in metrics + dimensions:
                raise PlanRejected("排序字段未被选择")
            order = plan.order_by.replace(".", "__")
            sql += f" ORDER BY {order} {'DESC' if plan.descending else 'ASC'}"
        sql += f" LIMIT {plan.limit}"
        # Validate trusted formulas too. Return original text for named bindings.
        SQLGuard(self.policy["tables"]).validate(sql)
        return CompiledQuery(sql, params, definitions, self.rules["version"])
