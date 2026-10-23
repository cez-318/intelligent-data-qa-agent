import asyncio
import json
import httpx
import pytest
from improved.tei import TEIEmbeddings


def test_local_tei_protocol_sync_and_async():
    def handler(request):
        assert request.url.path == "/embed"
        payload = json.loads(request.content)
        assert payload["inputs"] == ["省份"]
        assert payload["normalize"] is True
        return httpx.Response(200, json=[[0.1, 0.2]])
    client = TEIEmbeddings("http://127.0.0.1:18080", 2, transport=httpx.MockTransport(handler))
    assert client.embed_query("省份") == [0.1, 0.2]
    assert asyncio.run(client.aembed_query("省份")) == [0.1, 0.2]


@pytest.mark.parametrize("payload", [[], [[1]], [[True, 1]], [["x", 1]], [[1, 2], [3, 4]]])
def test_tei_rejects_invalid_vectors(payload):
    client = TEIEmbeddings("http://127.0.0.1:18080", 2, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    with pytest.raises(ValueError, match="INVALID_EMBEDDING_RESPONSE"):
        asyncio.run(client.aembed_query("测试"))


def test_empty_embedding_batch_does_not_call_service():
    client = TEIEmbeddings("http://127.0.0.1:18080", 2)
    assert client.embed_documents([]) == []
    assert asyncio.run(client.aembed_documents([])) == []


@pytest.mark.parametrize("asynchronous", [False, True])
def test_large_batch_is_split_to_fit_cpu_tei_queue(asynchronous):
    calls = []
    def handler(request):
        texts = json.loads(request.content)["inputs"]
        calls.append(texts)
        assert len(texts) <= 4
        return httpx.Response(200, json=[[float(text), 0] for text in texts])
    client = TEIEmbeddings("http://127.0.0.1:18080", 2, transport=httpx.MockTransport(handler))
    texts = [str(i) for i in range(10)]
    result = asyncio.run(client.aembed_documents(texts)) if asynchronous else client.embed_documents(texts)
    assert [row[0] for row in result] == list(range(10))
    assert len(calls) == 3
