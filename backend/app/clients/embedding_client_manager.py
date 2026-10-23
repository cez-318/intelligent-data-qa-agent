from typing import Optional

from improved.tei import TEIEmbeddings

from app.conf.app_config import EmbeddingConfig, app_config


class EmbeddingClientManager:
    def __init__(self, config: EmbeddingConfig):
        self.client: Optional[TEIEmbeddings] = None
        self.config = config

    def _get_url(self):
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        self.client = TEIEmbeddings(self._get_url(), app_config.qdrant.embedding_size)


embedding_client_manager = EmbeddingClientManager(app_config.embedding)
