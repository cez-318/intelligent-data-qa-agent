"""Closed-vocabulary dependency diagnostics; never serialize upstream exceptions."""
import asyncio
import logging
import random
import re
from time import perf_counter

import httpx
from elastic_transport import ConnectionError as ESConnectionError, ConnectionTimeout
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.core.context import request_id_ctx_var

STAGES = frozenset({
    "expand_columns", "expand_values", "expand_metrics", "select_columns",
    "select_metrics", "plan_query", "repair_intent", "column_embedding", "metric_embedding",
    "column_search", "metric_search", "value_search",
})
MARKERS = frozenset({
    "INVALID_KEYWORD_RESPONSE", "INVALID_METRIC_SELECTION", "INVALID_FIELD_SELECTION",
    "INVALID_EMBEDDING_RESPONSE", "INVALID_EMBEDDING_INPUT",
})
logger = logging.getLogger(__name__)


class StageFailure(Exception):
    def __init__(self, stage, code):
        self.stage = stage if stage in STAGES else "unknown"
        self.code = code if code in CODES else "INTERNAL_ERROR"
        super().__init__(self.code)


CODES = MARKERS | frozenset({
    "TIMEOUT", "UPSTREAM_TIMEOUT", "UPSTREAM_CONNECTION", "UPSTREAM_RATE_LIMIT",
    "UPSTREAM_AUTH", "UPSTREAM_UNAVAILABLE", "UPSTREAM_HTTP", "MODEL_CONNECTION",
    "MODEL_AUTH", "MODEL_JSON_INVALID", "RETRIEVAL_TRANSPORT", "INTERNAL_ERROR",
})


def request_id():
    value = str(request_id_ctx_var.get())
    return value if re.fullmatch(r"[a-f0-9]{32}", value) else "unavailable"


def failure_code(error):
    if isinstance(error, StageFailure):
        return error.code
    if isinstance(error, ResponseHandlingException):
        source = error.source
        if isinstance(source, httpx.TransportError):
            return failure_code(source)
        return "RETRIEVAL_TRANSPORT"
    if type(error) is ValueError and str(error) in MARKERS:
        return str(error)
    if isinstance(error, (httpx.TimeoutException, ConnectionTimeout)):
        return "UPSTREAM_TIMEOUT"
    if isinstance(error, (httpx.TransportError, ESConnectionError)):
        return "UPSTREAM_CONNECTION"
    # langchain-openai exposes subclasses whose names differ from the base
    # openai exceptions. Use inheritance so SDK upgrades retain the same
    # closed-vocabulary diagnostics without serializing provider messages.
    try:
        import openai
        if isinstance(error, openai.APITimeoutError):
            return "UPSTREAM_TIMEOUT"
        if isinstance(error, openai.AuthenticationError):
            return "MODEL_AUTH"
        if isinstance(error, openai.RateLimitError):
            return "UPSTREAM_RATE_LIMIT"
        if isinstance(error, openai.APIConnectionError):
            return "MODEL_CONNECTION"
    except ImportError:
        pass
    status = None
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
    elif isinstance(error, UnexpectedResponse):
        status = error.status_code
    else:
        # Status only; never stringify bodies, URLs, SQL or exception messages.
        from elasticsearch import ApiError
        if isinstance(error, ApiError):
            status = error.status_code
    if status is not None:
        return {401: "UPSTREAM_AUTH", 403: "UPSTREAM_AUTH", 429: "UPSTREAM_RATE_LIMIT",
                502: "UPSTREAM_UNAVAILABLE", 503: "UPSTREAM_UNAVAILABLE",
                504: "UPSTREAM_TIMEOUT"}.get(status, "UPSTREAM_HTTP")
    return {"TimeoutError": "TIMEOUT", "RateLimitError": "UPSTREAM_RATE_LIMIT",
            "APIConnectionError": "MODEL_CONNECTION", "APITimeoutError": "UPSTREAM_TIMEOUT",
            "AuthenticationError": "MODEL_AUTH", "OutputParserException": "MODEL_JSON_INVALID"}.get(
                type(error).__name__, "INTERNAL_ERROR")


def transient_read_failure(error):
    """Retry only identified transport failures/502-504, never auth, 429 or bad data."""
    if isinstance(error, ResponseHandlingException):
        error = error.source
    if isinstance(error, (httpx.TransportError, ESConnectionError, ConnectionTimeout)):
        return True
    try:
        import openai
        if isinstance(error, (openai.APIConnectionError, openai.APITimeoutError)):
            return True
    except ImportError:
        pass
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {502, 503, 504}
    if isinstance(error, UnexpectedResponse):
        return error.status_code in {502, 503, 504}
    from elasticsearch import ApiError
    return isinstance(error, ApiError) and error.status_code in {502, 503, 504}


async def observed_call(stage, operation, *, retry_read=False, timeout=None):
    if stage not in STAGES:
        raise ValueError("INVALID_DIAGNOSTIC_STAGE")
    started = perf_counter()
    attempts = 0
    try:
        async with asyncio.timeout(timeout):
            while True:
                attempts += 1
                try:
                    result = await operation()
                    break
                except Exception as error:
                    if not retry_read or attempts >= 2 or not transient_read_failure(error):
                        raise
                    logger.warning("dependency_retry request_id=%s stage=%s code=%s attempt=%d",
                                   request_id(), stage, failure_code(error), attempts)
                    await asyncio.sleep(random.uniform(0.1, 0.3))
    except asyncio.CancelledError:
        logger.info("dependency_cancelled request_id=%s stage=%s", request_id(), stage)
        raise
    except Exception as error:
        code = failure_code(error)
        logger.warning("dependency_failed request_id=%s stage=%s code=%s attempts=%d elapsed_ms=%d",
                       request_id(), stage, code, attempts, int((perf_counter() - started) * 1000))
        raise StageFailure(stage, code) from None
    logger.info("dependency_ok request_id=%s stage=%s attempts=%d elapsed_ms=%d",
                request_id(), stage, attempts, int((perf_counter() - started) * 1000))
    return result
