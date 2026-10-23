import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from tests.legacy.demo_app import create_app
from tests.legacy.demo import seed_demo, SQLiteRepository, DemoService
from tests.legacy.semantic import SemanticCatalog, Clarification, previous_month, compare_values
from improved.guard import QueryRejected, SQLGuard
from tests.legacy.workflow import run_validated_query
from improved.auth import query_rate_limit, _recent
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository


@pytest.mark.parametrize("sql", ["", "x" * 20001, "SELECT x FROM t LIMIT 2 OFFSET -1", "SELECT x FROM t LIMIT 2 OFFSET 9999", "SELECT ("])
def test_guard_edge_inputs(sql):
    with pytest.raises(QueryRejected):
        SQLGuard({"t": ["x"]}).validate(sql)


def test_safe_offset_and_existing_small_limit():
    assert "LIMIT 2 OFFSET 1" in SQLGuard({"t": ["x"]}).validate("SELECT x FROM t LIMIT 2 OFFSET 1")


def test_zero_missing_and_rate_comparisons():
    assert previous_month("2026-01-01") == "2025-12-01"
    assert compare_values(5, 0)["change_percent"] is None
    assert compare_values(5, None)["difference"] is None
    assert compare_values(5, 2, is_rate=True)["unit"] == "百分点"
    with pytest.raises(Clarification):
        SemanticCatalog().parse("2026年9月人力部研发部入职人数")


def test_database_not_overwritten_and_timeout(tmp_path):
    db = tmp_path / "test.sqlite3"
    seed_demo(db)
    with pytest.raises(FileExistsError):
        seed_demo(db)
    repo = SQLiteRepository(db, timeout_seconds=-1)
    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        with repo.connect() as connection:
            connection.execute("SELECT COUNT(*) FROM hr_monthly a, hr_monthly b, hr_monthly c").fetchone()


def test_grouped_comparison(tmp_path):
    db = tmp_path / "test.sqlite3"
    seed_demo(db)
    result = asyncio.run(DemoService(db).ask("2026年9月各部门离职率环比"))
    assert len(result["analysis"]) == 3
    assert all(r["unit"] == "百分点" for r in result["analysis"])


def test_api_failure_is_generic_and_rate_limited(tmp_path, monkeypatch):
    with TestClient(create_app(tmp_path / "missing.sqlite3")) as client:
        assert client.get("/api/health").json()["llm_enabled"] is False
        result = client.post("/api/query", json={"query": "2026年9月入职人数"})
        assert "missing.sqlite3" not in result.text
        assert '"type": "error"' in result.text
        for _ in range(29):
            client.post("/api/query", json={"query": "不支持"})
        assert client.post("/api/query", json={"query": "不支持"}).status_code == 429
        monkeypatch.setattr("tests.legacy.demo_app.time.monotonic", lambda: 10**12)
        assert client.post("/api/query", json={"query": "不支持"}).status_code == 200


def test_original_rate_limit(monkeypatch):
    _recent.clear()
    for _ in range(30):
        asyncio.run(query_rate_limit())
    with pytest.raises(HTTPException) as error:
        asyncio.run(query_rate_limit())
    assert error.value.status_code == 429
    monkeypatch.setattr("improved.auth.time.monotonic", lambda: 10**12)
    asyncio.run(query_rate_limit())
    _recent.clear()


def test_mysql_metadata_uses_allowlist_and_bound_limit():
    session = SimpleNamespace(execute=AsyncMock(), invalidate=AsyncMock())
    session.execute.return_value = MagicMock()
    repo = DWMySQLRepository(session, {"tables": {"t": ["id"]}})
    session.execute.return_value.fetchall.return_value = [SimpleNamespace(Field="id", Type="int"), SimpleNamespace(Field="salary", Type="int")]
    assert asyncio.run(repo.get_column_types("t")) == {"id": "int"}
    session.execute.return_value.scalars.return_value.fetchall.return_value = [1]
    assert asyncio.run(repo.get_column_values("t", "id", 999999)) == [1]
    assert session.execute.call_args.args[1] == {"limit": 1000}
    with pytest.raises(QueryRejected):
        asyncio.run(repo.get_column_values("t", "secret", 10))
    assert asyncio.run(repo.get_db_info())["dialect"] == "mysql"
    asyncio.run(repo.validate_sql("SELECT id FROM t"))
    assert "EXPLAIN SELECT" in str(session.execute.call_args.args[0])
    assert DWMySQLRepository(session).guard.schema
    with pytest.raises(ValueError):
        DWMySQLRepository(session, {"tables": {}, "timeout_ms": 0})


@pytest.mark.parametrize("method", ["validate_sql", "execute_sql"])
def test_mysql_timeout_invalidates_connection(method):
    session = SimpleNamespace(execute=AsyncMock(side_effect=TimeoutError), invalidate=AsyncMock())
    repo = DWMySQLRepository(session, {"tables": {"t": ["id"]}})
    with pytest.raises(QueryRejected, match="QUERY_TIMEOUT"):
        asyncio.run(getattr(repo, method)("SELECT id FROM t"))
    session.invalidate.assert_awaited_once()


def test_retry_parameter_range():
    with pytest.raises(ValueError):
        asyncio.run(run_validated_query(None, "", max_attempts=0))
