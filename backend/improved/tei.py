"""Typed local TEI adapter; never redirects embedding requests to a cloud model."""
import math
import httpx
from langchain_core.embeddings import Embeddings


class TEIEmbeddings(Embeddings):
    def __init__(self, base_url, dimensions, *, transport=None):
        self.base_url = base_url.rstrip("/")
        self.dimensions = dimensions
        self.transport = transport

    def _validate(self, data, count):
        if not isinstance(data, list) or len(data) != count:
            raise ValueError("INVALID_EMBEDDING_RESPONSE")
        for row in data:
            if (not isinstance(row, list) or len(row) != self.dimensions or
                    any(type(value) not in (int, float) or not math.isfinite(value) for value in row)):
                raise ValueError("INVALID_EMBEDDING_RESPONSE")
        return data

    def _payload(self, texts):
        if len(texts) > 32 or any(not isinstance(text, str) or not text or len(text) > 8000 for text in texts):
            raise ValueError("INVALID_EMBEDDING_INPUT")
        return {"inputs": [text.replace("\n", " ") for text in texts], "normalize": True, "truncate": True}

    def embed_documents(self, texts):
        if not texts:
            return []
        with httpx.Client(timeout=httpx.Timeout(20, connect=3), transport=self.transport, trust_env=False) as client:
            result = []
            self._payload(texts)  # Validate the whole request before sending any batch.
            for start in range(0, len(texts), 4):
                batch = texts[start:start + 4]
                response = client.post(self.base_url + "/embed", json=self._payload(batch))
                response.raise_for_status()
                result.extend(self._validate(response.json(), len(batch)))
            return result

    async def aembed_documents(self, texts):
        if not texts:
            return []
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=3), transport=self.transport, trust_env=False) as client:
            result = []
            self._payload(texts)
            for start in range(0, len(texts), 4):
                batch = texts[start:start + 4]
                response = await client.post(self.base_url + "/embed", json=self._payload(batch))
                response.raise_for_status()
                result.extend(self._validate(response.json(), len(batch)))
            return result

    def embed_query(self, text):
        return self.embed_documents([text])[0]

    async def aembed_query(self, text):
        return (await self.aembed_documents([text]))[0]
