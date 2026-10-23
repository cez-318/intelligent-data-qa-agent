import asyncio
import json
from unittest.mock import patch
import pytest
from app.services.query_service import QueryService, failure_code


@pytest.mark.parametrize('error,expected', [
    (ValueError('INVALID_KEYWORD_RESPONSE'),'INVALID_KEYWORD_RESPONSE'),
    (ValueError('private business record / secret'),'INTERNAL_ERROR'),
    (TimeoutError('secret'),'TIMEOUT'),
])
def test_diagnostics_are_allowlisted(error, expected):
    assert failure_code(error) == expected


def test_failure_does_not_publish_exception_text(caplog):
    async def failed(*args, **kwargs):
        yield {'type':'progress','step':'召回字段','status':'running'}
        raise ValueError('secret-token-and-private-record')
    service = QueryService(*([None]*6))
    async def collect():
        with patch('app.services.query_service.graph.astream', failed):
            return [json.loads(c[6:]) async for c in service.query('private question')]
    events = asyncio.run(collect())
    assert events[-1]['code'] == 'INTERNAL_ERROR'
    assert 'secret-token' not in json.dumps(events) + caplog.text
    assert 'private question' not in caplog.text
