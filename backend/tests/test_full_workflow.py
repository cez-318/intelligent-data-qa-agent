import asyncio
import json
from pathlib import Path
import pytest
from app.agent.graph import graph
from app.services.query_service import QueryService
from tests.support.ecommerce import Warehouse, Metadata, Retriever, Embedding, ScriptedModel


@pytest.fixture
def full_pipeline(tmp_path, monkeypatch):
    warehouse, metadata = Warehouse(tmp_path / "example.sqlite3"), Metadata()
    columns, metrics, values = Retriever(list(metadata.columns.values())), Retriever(metadata.metrics), Retriever([])
    service = QueryService(Embedding(), columns, values, metrics, metadata, warehouse)
    def run(decision, question="请分析今年的订单数据"):
        model = ScriptedModel(decision)
        monkeypatch.setattr("app.agent.llm.get_model", lambda: model)
        async def collect():
            return [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in service.query(question)]
        events = asyncio.run(collect())
        return events, model, warehouse, (columns, metrics, values)
    run.warehouse = warehouse
    return run


def test_full_graph_repairs_and_revalidates(full_pipeline):
    full_pipeline.warehouse.fail_validation_once = True
    events, model, database, _ = full_pipeline({"mode": "metric", "plan": {"metrics": ["GMV"]}})
    assert any(event["type"] == "result" for event in events)
    assert database.validations == 2 and database.executions == 1
    assert model.calls.count("plan_query") == 2


def test_full_graph_empty_period_is_not_zero(full_pipeline):
    events, _, _, _ = full_pipeline({"mode": "metric", "plan": {"metrics": ["GMV"], "filters": [{"field": "dim_date.year", "op": "eq", "value": 1900}]}})
    assert next(event for event in events if event["type"] == "result")["data"] == []


def test_context_preserves_retrieved_values():
    from improved.context import enrich_context
    tables, _ = enrich_context([{"name": "dim_region", "columns": [{"name": "province", "type": "varchar", "examples": ["广东"], "description": "地区"}]}], [])
    column = next(c for c in tables[0]["columns"] if c["name"] == "province")
    assert column["examples"] == ["广东"]
    assert column["type"] == "varchar"


@pytest.mark.parametrize("metric,expected", [("GMV", 600), ("AOV", 200)])
def test_original_full_graph_computes_registered_metrics(full_pipeline, metric, expected):
    events, model, database, retrievers = full_pipeline({"mode": "metric", "plan": {"metrics": [metric], "filters": [{"field": "dim_date.year", "op": "eq", "value": 2026}]}})
    result = next(event for event in events if event["type"] == "result")
    assert result["data"] == [{metric: expected}]
    assert result["evidence"]["mode"] == "llm_rag"
    assert all(retriever.calls > 0 for retriever in retrievers)
    assert set(model.calls) >= {"expand_columns", "expand_metrics", "expand_values", "select_columns", "select_metrics", "plan_query"}
    assert database.executions == 1


def test_original_full_graph_comparison(full_pipeline):
    events, _, database, _ = full_pipeline({"mode": "metric", "plan": {"metrics": ["GMV"], "dimensions": ["dim_region.province"],
              "filters": [{"field": "dim_date.year", "op": "eq", "value": 2026}],
              "comparison_filters": [{"field": "dim_date.year", "op": "eq", "value": 2025}]}})
    result = next(event for event in events if event["type"] == "result")
    changes = {item["dim_region__province"]: item["metrics"]["GMV"]["change_percent"] for item in result["analysis"]}
    assert changes == {"广东": 300, "北京": 100}
    assert database.validations == 2 and database.executions == 2


def test_original_full_graph_clarifies_without_execution(full_pipeline):
    events, _, database, _ = full_pipeline({"mode": "clarify", "message": "需要哪一个统计周期？"}, "最近怎么样？")
    assert events[-1]["type"] == "clarification"
    assert database.executions == 0


def test_original_full_graph_rejects_dangerous_sql(full_pipeline):
    events, _, database, _ = full_pipeline({"mode": "sql", "sql": "DELETE FROM fact_order"})
    assert events[-1]["type"] == "error"
    assert database.executions == 0


def test_original_full_graph_detail_query(full_pipeline):
    events, _, _, _ = full_pipeline({"mode": "sql", "sql": "SELECT order_id, order_amount FROM fact_order WHERE order_id = 1"})
    assert next(event for event in events if event["type"] == "result")["data"] == [{"order_id": 1, "order_amount": 100}]


def test_production_entry_has_no_rule_fallback(monkeypatch):
    from fastapi.testclient import TestClient
    import app.core.lifespan as lifecycle
    from main import create_app
    monkeypatch.setattr(lifecycle, "missing_configuration", lambda _: ["LLM_API_KEY"])
    with TestClient(create_app()) as client:
        health = client.get("/api/health").json()
        assert health["mode"] == "llm_rag" and health["rule_fallback"] is False
        assert client.post("/api/query", json={"query": "2026年销售额"}).status_code == 503
        assert client.get("/").status_code == 200


def test_production_api_streams_original_graph(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import app.core.lifespan as lifecycle
    from app.api.dependencies import get_query_service
    from main import create_app
    metadata, database = Metadata(), Warehouse(tmp_path / "api.sqlite3")
    service = QueryService(Embedding(), Retriever(list(metadata.columns.values())), Retriever([]), Retriever(metadata.metrics), metadata, database)
    model = ScriptedModel({"mode": "metric", "plan": {"metrics": ["GMV"]}})
    monkeypatch.setattr("app.agent.llm.get_model", lambda: model)
    monkeypatch.setattr(lifecycle, "missing_configuration", lambda _: ["TEST_ADAPTERS"])
    monkeypatch.setenv("DATA_AGENT_API_TOKEN", "test-only")
    app = create_app()
    app.dependency_overrides[get_query_service] = lambda: service
    with TestClient(app) as client:
        app.state.ready = True
        assert client.post("/api/query", json={"query": "成交总额"}).status_code == 401
        response = client.post("/api/query", json={"query": "成交总额"}, headers={"Authorization": "Bearer test-only"})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-request-id"]
        events = [json.loads(chunk[6:]) for chunk in response.text.strip().split("\n\n")]
        assert next(e for e in events if e["type"] == "result")["data"] == [{"GMV": 800}]


@pytest.mark.parametrize("decision", [
    {"mode": "metric"}, {"mode": "metric", "plan": {"metrics": ["unregistered"]}},
    {"mode": "sql", "sql": "SELECT SUM(order_amount) FROM fact_order"},
])
def test_full_graph_invalid_decision_never_executes(full_pipeline, decision):
    events, _, database, _ = full_pipeline(decision)
    assert events[-1]["type"] == "clarification"
    assert database.executions == 0
