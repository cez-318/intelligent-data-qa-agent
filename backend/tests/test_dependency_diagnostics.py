import asyncio
import json
import logging
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.context import request_id_ctx_var
from app.services.query_service import QueryService
from improved.diagnostics import StageFailure, failure_code, observed_call


@pytest.mark.parametrize("status,code,retries", [
    (401, "UPSTREAM_AUTH", 1), (403, "UPSTREAM_AUTH", 1),
    (404, "UPSTREAM_HTTP", 1), (429, "UPSTREAM_RATE_LIMIT", 1),
    (502, "UPSTREAM_UNAVAILABLE", 2), (503, "UPSTREAM_UNAVAILABLE", 2),
    (504, "UPSTREAM_TIMEOUT", 2),
])
@pytest.mark.parametrize("provider", ["httpx", "qdrant"])
def test_status_classification_and_bounded_retry(status, code, retries, provider, caplog):
    response = httpx.Response(status, request=httpx.Request("POST", "http://local.invalid/private"), text="private-token")
    error = (httpx.HTTPStatusError("private-response", request=response.request, response=response)
             if provider == "httpx" else UnexpectedResponse.for_response(response))
    operation = AsyncMock(side_effect=error)
    with pytest.raises(StageFailure) as caught:
        asyncio.run(observed_call("value_search", operation, retry_read=True))
    assert caught.value.code == code
    assert operation.await_count == retries
    assert "private" not in caplog.text + str(caught.value)


def test_transient_read_recovers_without_fabricating_result():
    operation = AsyncMock(side_effect=[ResponseHandlingException(httpx.ConnectError("secret")), ["actual-result"]])
    assert asyncio.run(observed_call("column_search", operation, retry_read=True)) == ["actual-result"]
    assert operation.await_count == 2


def test_model_boundary_does_not_multiply_provider_retries():
    operation = AsyncMock(side_effect=httpx.ConnectError("secret"))
    with pytest.raises(StageFailure):
        asyncio.run(observed_call("plan_query", operation))
    assert operation.await_count == 1


def test_invalid_payload_is_not_retried():
    operation = AsyncMock(side_effect=ValueError("INVALID_EMBEDDING_RESPONSE"))
    with pytest.raises(StageFailure) as caught:
        asyncio.run(observed_call("metric_embedding", operation, retry_read=True))
    assert caught.value.code == "INVALID_EMBEDDING_RESPONSE"
    assert operation.await_count == 1


def test_deadline_cancels_inflight_read_before_failure():
    async def scenario():
        cleaned = asyncio.Event()

        async def slow():
            try:
                await asyncio.Event().wait()
            finally:
                cleaned.set()

        with pytest.raises(StageFailure) as caught:
            await observed_call("value_search", slow, timeout=0.01, retry_read=True)
        assert caught.value.code == "TIMEOUT"
        assert cleaned.is_set()

    asyncio.run(scenario())


def test_caller_cancellation_is_never_swallowed_or_retried():
    async def scenario():
        started = asyncio.Event()

        async def pending():
            started.set()
            await asyncio.Event().wait()

        operation = AsyncMock(side_effect=pending)
        task = asyncio.create_task(observed_call("column_embedding", operation, retry_read=True))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert operation.await_count == 1

    asyncio.run(scenario())


def test_request_trace_survives_stream_and_is_logged(caplog):
    async def failed(*args, **kwargs):
        yield {"type": "progress", "step": "召回字段", "status": "running"}
        raise StageFailure("column_search", "UPSTREAM_TIMEOUT")

    async def collect():
        token = request_id_ctx_var.set("a" * 32)
        try:
            with patch("app.services.query_service.graph.astream", failed):
                return [json.loads(chunk[6:]) async for chunk in QueryService(*([None] * 6)).query("private-question")]
        finally:
            request_id_ctx_var.reset(token)

    events = asyncio.run(collect())
    assert events[-1]["request_id"] == "a" * 32
    assert events[-1]["stage"] == "column_search"
    assert events[-1]["code"] == "UPSTREAM_TIMEOUT"
    assert "a" * 32 in caplog.text
    assert "private-question" not in caplog.text


def test_diagnostic_values_cannot_inject_logs(caplog):
    caplog.set_level(logging.INFO)
    token = request_id_ctx_var.set("secret\nforged-log")
    try:
        assert asyncio.run(observed_call("value_search", AsyncMock(return_value=[]))) == []
        with pytest.raises(ValueError, match="INVALID_DIAGNOSTIC_STAGE"):
            asyncio.run(observed_call("secret\nforged-log", AsyncMock()))
    finally:
        request_id_ctx_var.reset(token)
    assert "secret" not in caplog.text
    assert "request_id=unavailable" in caplog.text


def test_unknown_wrapped_errors_are_not_stringified():
    assert failure_code(ResponseHandlingException(ValueError("secret"))) == "RETRIEVAL_TRANSPORT"
    assert failure_code(StageFailure("secret", "secret")) == "INTERNAL_ERROR"


def test_elasticsearch_status_and_connection_errors():
    from elasticsearch import ApiError
    from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig, ConnectionError, ConnectionTimeout
    meta = ApiResponseMeta(status=503, http_version="1.1", headers=HttpHeaders(), duration=0.1,
                           node=NodeConfig("http", "localhost", 9200))
    error = ApiError("private-body", meta, {"secret": "private"})
    operation = AsyncMock(side_effect=error)
    with pytest.raises(StageFailure) as caught:
        asyncio.run(observed_call("value_search", operation, retry_read=True))
    assert caught.value.code == "UPSTREAM_UNAVAILABLE"
    assert operation.await_count == 2
    assert failure_code(ConnectionError("private")) == "UPSTREAM_CONNECTION"
    assert failure_code(ConnectionTimeout("private")) == "UPSTREAM_TIMEOUT"


@pytest.mark.parametrize("wrapped", [False, True])
@pytest.mark.parametrize("kind,expected", [
    ("connection", "MODEL_CONNECTION"), ("timeout", "UPSTREAM_TIMEOUT"),
    ("authentication", "MODEL_AUTH"), ("rate_limit", "UPSTREAM_RATE_LIMIT"),
])
def test_model_errors_include_provider_wrapper_subclasses(wrapped, kind, expected):
    import openai
    from langchain_openai.chat_models import base
    classes = {
        "connection": (openai.APIConnectionError, base.OpenAIConnectionError),
        "timeout": (openai.APITimeoutError, base.OpenAITimeoutError),
        "authentication": (openai.AuthenticationError, base.OpenAIAuthenticationError),
        "rate_limit": (openai.RateLimitError, base.OpenAIRateLimitError),
    }
    cls = classes[kind][int(wrapped)]
    request = httpx.Request("POST", "https://example.invalid/private")
    if kind in {"connection", "timeout"}:
        error = cls(request=request)
    else:
        status = 401 if kind == "authentication" else 429
        error = cls("private-message", response=httpx.Response(status, request=request), body={"secret": "private"})
    assert failure_code(error) == expected
