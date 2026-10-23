import json
import asyncio
import logging
from improved.diagnostics import StageFailure, failure_code, request_id

from langchain_core.embeddings import Embeddings

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


class QueryService:
    def __init__(self,
                 embedding_client: Embeddings,
                 column_qdrant_repository: ColumnQdrantRepository,
                 value_es_repository: ValueESRepository,
                 metric_qdrant_repository: MetricQdrantRepository,
                 meta_mysql_repository: MetaMySQLRepository,
                 dw_mysql_repository: DWMySQLRepository):
        self.embedding_client = embedding_client
        self.column_qdrant_repository = column_qdrant_repository
        self.value_es_repository = value_es_repository
        self.metric_qdrant_repository = metric_qdrant_repository
        self.meta_mysql_repository = meta_mysql_repository
        self.dw_mysql_repository = dw_mysql_repository

    async def query(self, query: str):
        context = DataAgentContext(
            embedding_client=self.embedding_client,
            column_qdrant_repository=self.column_qdrant_repository,
            value_es_repository=self.value_es_repository,
            metric_qdrant_repository=self.metric_qdrant_repository,
            meta_mysql_repository=self.meta_mysql_repository,
            dw_mysql_repository=self.dw_mysql_repository
        )
        state = DataAgentState(query=query)
        try:
            async with asyncio.timeout(60):
                async for chunk in graph.astream(input=state, context=context, stream_mode="custom"):
                    yield f"data: {json.dumps(chunk, ensure_ascii=False, default=str)}\n\n"
        except Exception as e:
            code = failure_code(e)
            stage = e.stage if isinstance(e, StageFailure) else 'unknown'
            trace = request_id()
            logging.getLogger(__name__).warning('query_failed request_id=%s stage=%s code=%s', trace, stage, code)
            event = {'type': 'error', 'code': code, 'stage': stage, 'request_id': trace,
                     'message': '查询未完成，请稍后重试或将诊断编号提供给维护者。'}
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
