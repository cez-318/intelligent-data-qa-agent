import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from improved.retrieval import bounded_search


def test_failed_batch_cancels_and_joins_remaining_searches():
    async def scenario():
        started, cleaned = asyncio.Event(), asyncio.Event()

        async def search(value):
            if value == 0:
                await started.wait()
                raise ValueError("private-upstream-response")
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        with pytest.raises(ValueError):
            await bounded_search([0, 1], search)
        assert cleaned.is_set(), "Failed request left a retrieval running in the background"

    asyncio.run(scenario())


def test_batch_preserves_order_and_bounds_concurrency():
    async def scenario():
        active = peak = 0

        async def search(value):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            active -= 1
            return value

        assert await bounded_search(range(20), search) == list(range(20))
        assert peak <= 4

    asyncio.run(scenario())


def test_cancelled_batch_cleans_children():
    async def scenario():
        started, cleaned = asyncio.Event(), asyncio.Event()

        async def search(_):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        task = asyncio.create_task(bounded_search([1], search))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_embedding_failure_identifies_stage_without_exposing_details(monkeypatch, caplog):
    from app.agent.nodes.recall_column import recall_column
    from app.services.query_service import failure_code

    monkeypatch.setattr("app.agent.nodes.recall_column.expanded_keywords", AsyncMock(return_value=["private-question"]))
    runtime = SimpleNamespace(
        stream_writer=lambda event: None,
        context={"embedding_client": SimpleNamespace(aembed_documents=AsyncMock(side_effect=httpx.ReadTimeout("secret-token")))},
    )
    with pytest.raises(Exception) as caught:
        asyncio.run(recall_column({"query": "private-question"}, runtime))
    assert getattr(caught.value, "stage", None) == "column_embedding"
    assert failure_code(caught.value) == "UPSTREAM_TIMEOUT"
    assert "secret-token" not in str(caught.value) + caplog.text
    assert "private-question" not in caplog.text
