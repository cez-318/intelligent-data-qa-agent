"""Bounded offline parser and reviewed SQL templates. Not an LLM accuracy benchmark."""
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
import yaml

METRICS_PATH = Path(__file__).resolve().parent / "demo_metrics.yaml"
DEPARTMENTS = {"人力部": 1, "研发部": 2, "销售部": 3}


class Clarification(ValueError):
    pass


@dataclass
class QueryPlan:
    metric: str
    month: str
    department: str | None = None
    group_by_department: bool = False
    compare: bool = False


class SemanticCatalog:
    def __init__(self):
        self.config = yaml.safe_load(METRICS_PATH.read_text(encoding="utf-8"))
        self.metrics = self.config["metrics"]

    def parse(self, question: str) -> QueryPlan:
        text = question.strip().replace(" ", "")
        months = list(re.finditer(r"(20\d{2})年(1[0-2]|0?[1-9])月", text))
        if len(months) != 1:
            raise Clarification("请明确一个月份，例如：2026年9月入职人数。演示数据覆盖2026年8、9月。")
        month = months[0]
        remainder = text[:month.start()] + text[month.end():]
        matches = []
        for key, metric in self.metrics.items():
            for alias in sorted(metric["aliases"], key=len, reverse=True):
                if alias in remainder:
                    matches.append((key, alias))
                    break
        if len(matches) != 1:
            raise Clarification("请一次选择一个指标：月末在职人数、入职人数、离职人数或离职率。")
        key, alias = matches[0]
        remainder = remainder.replace(alias, "", 1)
        group = "各部门" in remainder or "按部门" in remainder
        remainder = remainder.replace("各部门", "").replace("按部门", "")
        departments = [name for name in DEPARTMENTS if name in remainder]
        if len(departments) > 1 or (group and departments):
            raise Clarification("请指定一个部门，或使用各部门汇总。")
        department = departments[0] if departments else None
        if department:
            remainder = remainder.replace(department, "", 1)
        compare = "环比" in remainder
        remainder = remainder.replace("环比", "", 1)
        # Do not silently drop an unsupported condition such as city, gender, day or intern.
        if not re.fullmatch(r"(?:请|帮我|查询|统计|的|是多少|多少|情况|变化|[？?。，,])*", remainder):
            raise Clarification("该问题包含尚未支持的条件。演示支持指定月份、单个/各部门和环比；仅统计正式员工。")
        return QueryPlan(key, f"{int(month[1]):04d}-{int(month[2]):02d}-01", department, group, compare)

    def build(self, plan: QueryPlan, month: str | None = None):
        metric = self.metrics[plan.metric]
        dimension = "d.name AS department, " if plan.group_by_department else ""
        sql = f"SELECT {dimension}{metric['expression']} AS value, COUNT(*) AS sample_rows FROM hr_monthly m JOIN departments d ON m.department_id = d.id WHERE m.month = :month AND m.employment_type = :population"
        params = {"month": month or plan.month, "population": "正式"}
        if plan.department:
            sql += " AND d.id = :department_id"
            params["department_id"] = DEPARTMENTS[plan.department]
        if plan.group_by_department:
            sql += " GROUP BY d.id, d.name"
        sql += " HAVING COUNT(*) > 0"
        if plan.group_by_department:
            sql += " ORDER BY d.id"
        return sql, params


def previous_month(month: str) -> str:
    parsed = date.fromisoformat(month)
    return f"{parsed.year - 1}-12-01" if parsed.month == 1 else f"{parsed.year}-{parsed.month - 1:02d}-01"


def compare_values(current, previous, *, is_rate=False):
    if current is None or previous is None:
        return {"difference": None, "change_percent": None, "note": "基期或本期无有效数值"}
    difference = round(current - previous, 2)
    if is_rate:
        return {"difference": difference, "unit": "百分点", "change_percent": None}
    return {"difference": difference, "change_percent": None if previous == 0 else round(difference / previous * 100, 2),
            "note": "基期为零，不计算增长率" if previous == 0 else ""}
