import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest


def test_metadata_examples_are_json_safe_without_losing_decimal_precision():
    import json
    from decimal import Decimal
    from datetime import date, datetime
    from app.services.meta_knowledge_service import normalize_example
    values = [Decimal("1234567890123456.78"), date(2026, 9, 1), datetime(2026, 9, 1, 12, 30), None, 2]
    result = [normalize_example(value) for value in values]
    assert json.loads(json.dumps(result)) == ["1234567890123456.78", "2026-09-01", "2026-09-01T12:30:00", None, 2]


def test_value_repository_uses_configured_index(monkeypatch):
    from app.conf.app_config import app_config
    from app.repositories.es.value_es_repository import ValueESRepository
    monkeypatch.setattr(app_config.es, "index_name", "qa-test-values")
    assert ValueESRepository(AsyncMock()).index_name == "qa-test-values"


def test_bulk_errors_are_not_silently_accepted():
    from app.entities.value_info import ValueInfo
    from app.repositories.es.value_es_repository import ValueESRepository
    client = AsyncMock()
    client.bulk.return_value = {"errors": True}
    with pytest.raises(RuntimeError, match="VALUE_INDEX_WRITE_FAILED"):
        asyncio.run(ValueESRepository(client).index([ValueInfo(id="x", value="广东", column_id="dim_region.province")]))


def test_metadata_save_upserts_instead_of_duplicate_insert():
    from app.entities.table_info import TableInfo
    from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
    session = SimpleNamespace(merge=AsyncMock())
    async def save():
        repository = MetaMySQLRepository(session)
        for _ in range(2):
            await repository.save_table_infos([TableInfo(id="dim_region", name="dim_region", role="dim", description="区域")])
    asyncio.run(save())
    assert session.merge.await_count == 2


def test_column_vector_ids_are_repeatable():
    from app.entities.column_info import ColumnInfo
    from app.services.meta_knowledge_service import MetaKnowledgeService
    column = ColumnInfo(id="dim_region.province", name="province", type="varchar", role="dimension", examples=[], description="省份", alias=["省"], table_id="dim_region")
    vectors = AsyncMock()
    embed = AsyncMock()
    embed.aembed_documents.return_value = [[1.0]] * 3
    service = MetaKnowledgeService(None, None, vectors, embed, None, None)
    asyncio.run(service._save_column_info_to_qdrant([column]))
    asyncio.run(service._save_column_info_to_qdrant([column]))
    first, second = vectors.upsert.await_args_list
    assert first.args[0] == second.args[0]
