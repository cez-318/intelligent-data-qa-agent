import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import FastAPI, Depends
from fastapi.testclient import TestClient

from app.agent.nodes.validate_sql import validate_sql, validation_route, reject_sql
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from improved.guard import QueryRejected
from improved.auth import require_api_token
from improved.context import enrich_context


def test_original_node_retries_then_stops_without_error_leak():
    events = []
    runtime = SimpleNamespace(stream_writer=events.append, context={"dw_mysql_repository": SimpleNamespace(validate_sql=AsyncMock(side_effect=ValueError("password=secret")))})
    state = {"sql": "bad"}
    for expected in ["correct_sql", "correct_sql", "reject_sql"]:
        state.update(asyncio.run(validate_sql(state, runtime)))
        assert validation_route(state) == expected
    asyncio.run(reject_sql(state, runtime))
    assert "secret" not in str(state) + str(events)


def test_original_node_policy_denial_and_success():
    method = AsyncMock(side_effect=QueryRejected("denied"))
    runtime = SimpleNamespace(stream_writer=lambda x: None, context={"dw_mysql_repository": SimpleNamespace(validate_sql=method)})
    state = asyncio.run(validate_sql({"sql": "bad"}, runtime))
    assert validation_route(state) == "reject_sql"
    method.side_effect = None
    state = asyncio.run(validate_sql({"sql": "ok"}, runtime))
    assert validation_route(state) == "execute_sql"


def test_mysql_repository_applies_gate_before_db_and_limits_results():
    session = SimpleNamespace(execute=AsyncMock(), invalidate=AsyncMock())
    repo = DWMySQLRepository(session, {"tables": {"t": ["id"]}, "max_rows": 10})
    with pytest.raises(QueryRejected):
        asyncio.run(repo.execute_sql("DELETE FROM t"))
    session.execute.assert_not_called()
    result = MagicMock()
    result.mappings.return_value.fetchmany.return_value = [{"id": 1}]
    session.execute.return_value = result
    assert asyncio.run(repo.execute_sql("SELECT id FROM t")) == [{"id": 1}]
    assert "MAX_EXECUTION_TIME" in str(session.execute.call_args_list[0].args[0])
    assert "LIMIT 10" in str(session.execute.call_args_list[-1].args[0])


def test_context_restores_bridge_keys_and_excludes_private_columns():
    tables = [{"name": "dim_region", "columns": [{"name": "province"}]},
              {"name": "dim_product", "columns": [{"name": "category"}]}]
    enriched, metrics = enrich_context(tables, [{"name": "AOV"}])
    names = {t["name"] for t in enriched}
    assert {"dim_region", "dim_product", "fact_order"} <= names
    fact = next(t for t in enriched if t["name"] == "fact_order")
    assert {"order_id", "region_id", "product_id", "order_amount"} <= {c["name"] for c in fact["columns"]}
    assert "COUNT(DISTINCT" in metrics[0]["expression"]


def test_auth_fails_closed(monkeypatch):
    app = FastAPI()
    @app.get("/protected", dependencies=[Depends(require_api_token)])
    def protected():
        return {"ok": True}
    client = TestClient(app)
    monkeypatch.delenv("DATA_AGENT_API_TOKEN", raising=False)
    assert client.get("/protected").status_code == 503
    monkeypatch.setenv("DATA_AGENT_API_TOKEN", "test-token-only")
    assert client.get("/protected").status_code == 401
    assert client.get("/protected", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/protected", headers={"Authorization": "Bearer test-token-only"}).status_code == 200
