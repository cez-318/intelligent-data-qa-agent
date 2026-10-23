import pytest
from pydantic import ValidationError
from improved.compiler import QueryPlan, SemanticCompiler, PlanRejected


def test_metric_formula_comes_from_registry_not_model():
    plan = QueryPlan(metrics=["AOV"], dimensions=["dim_region.province"],
                     filters=[{"field": "dim_date.year", "op": "eq", "value": 2026}])
    compiled = SemanticCompiler().compile(plan)
    assert "COUNT(DISTINCT fact_order.order_id)" in compiled.sql
    assert "JOIN dim_date" in compiled.sql
    assert "JOIN dim_region" in compiled.sql
    assert compiled.params == {"p0": 2026}
    assert "2026" not in compiled.sql


def test_filters_never_become_sql_code():
    payload = "x' OR 1=1 --"
    plan = QueryPlan(metrics=["GMV"], filters=[{"field": "dim_region.province", "op": "eq", "value": payload}])
    compiled = SemanticCompiler().compile(plan)
    assert payload not in compiled.sql
    assert compiled.params["p0"] == payload


@pytest.mark.parametrize("data", [
    {"metrics": ["salary"]},
    {"metrics": ["GMV"], "dimensions": ["dim_customer.customer_name"]},
    {"metrics": ["GMV"], "filters": [{"field": "dim_customer.gender", "op": "eq", "value": "x"}]},
    {"metrics": ["GMV"], "filters": [{"field": "dim_date.year", "op": "in", "value": []}]},
])
def test_unknown_semantics_rejected(data):
    with pytest.raises((PlanRejected, ValidationError)):
        SemanticCompiler().compile(QueryPlan(**data))


def test_comparison_uses_explicit_second_filter_set():
    plan = QueryPlan(metrics=["GMV"], filters=[{"field": "dim_date.year", "op": "eq", "value": 2026}],
                     comparison_filters=[{"field": "dim_date.year", "op": "eq", "value": 2025}])
    compiler = SemanticCompiler()
    assert compiler.compile(plan).params["p0"] == 2026
    assert compiler.compile(plan, comparison=True).params["p0"] == 2025
