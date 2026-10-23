"""Read-only checks for the isolated fictional warehouse and actual RAG services."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.conf.app_config import app_config
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from improved.compiler import SemanticCompiler, QueryPlan


async def check():
    assert all(c.host == "127.0.0.1" and c.port == 13306 for c in (app_config.db_meta, app_config.db_dw))
    assert (app_config.db_meta.database, app_config.db_dw.database) == ("meta", "dw")
    assert all(c.host == "127.0.0.1" for c in (app_config.es, app_config.qdrant, app_config.embedding))
    assert (app_config.es.port, app_config.qdrant.port, app_config.embedding.port) == (19200, 16333, 18080)
    managers = (meta_mysql_client_manager, dw_mysql_client_manager, es_client_manager, qdrant_client_manager)
    try:
        for manager in managers:
            manager.init()
        embedding_client_manager.init()
        counts = {}
        async with dw_mysql_client_manager.session_factory() as session:
            marker = (await session.execute(text("SELECT dataset FROM qa_fixture_manifest"))).scalars().all()
            assert marker == ["fictional_ecommerce_v1_five_orders"]
            assert (await session.execute(text("SELECT COUNT(*) FROM fact_order"))).scalar_one() == 5
            repo = DWMySQLRepository(session)
            compiled = SemanticCompiler().compile(QueryPlan(metrics=["GMV", "AOV"], filters=[{"field": "dim_date.year", "op": "eq", "value": 2026}]))
            await repo.validate_sql(compiled.sql, compiled.params)
            rows = await repo.execute_sql(compiled.sql, compiled.params)
            row = {key.lower(): value for key, value in rows[0].items()}
            assert row["gmv"] == Decimal("600") and row["aov"] == Decimal("200")
        async with meta_mysql_client_manager.session_factory() as session:
            for table in ("table_info", "column_info", "metric_info", "column_metric"):
                counts["meta_" + table] = (await session.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one()
            denied = (await session.execute(text("SELECT COUNT(*) FROM column_info WHERE id IN ('dim_customer.customer_name','dim_customer.gender')"))).scalar_one()
            assert denied == 0
        client = qdrant_client_manager.client
        for name in (ColumnQdrantRepository.collection_name, MetricQdrantRepository.collection_name):
            counts[name] = (await client.count(name, exact=True)).count
        counts["es_values"] = (await es_client_manager.client.count(index=app_config.es.index_name))["count"]
        vectors = await embedding_client_manager.client.aembed_documents(["订单金额", "成交总额"])
        assert len(vectors[0]) == 1024
        columns = await ColumnQdrantRepository(client).search(vectors[0])
        metrics = await MetricQdrantRepository(client).search(vectors[1])
        values = await ValueESRepository(es_client_manager.client).search("广东")
        assert "fact_order.order_amount" in {item.id for item in columns}
        assert "GMV" in {item.id for item in metrics}
        assert any(item.column_id == "dim_region.province" and item.value == "广东" for item in values)
        return {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "passed": True,
                "fixture": marker[0], "counts": counts, "mysql_2026_gmv": 600, "mysql_2026_aov": 200,
                "embedding_dimensions": 1024, "column_retrieval": True, "metric_retrieval": True,
                "value_retrieval": True, "sensitive_columns_excluded_from_metadata": True,
                "llm_called": False}
    finally:
        await asyncio.gather(*(manager.close() for manager in managers), return_exceptions=True)


if __name__ == "__main__":
    try:
        report = asyncio.run(check())
        (ROOT / "reports" / "local_stack.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    except Exception as error:
        raise SystemExit(f"Local stack check failed ({type(error).__name__}); credentials were not displayed.") from None
