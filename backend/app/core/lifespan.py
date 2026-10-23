import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import meta_mysql_client_manager, dw_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.conf.app_config import app_config
from improved.settings import missing_configuration
from improved.profiles import active_profile


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ready = False
    app.state.missing_configuration = missing_configuration(app_config)
    app.state.service_error = None
    initialized = []
    try:
        if not app.state.missing_configuration:
            try:
                embedding_client_manager.init()
                for manager in (qdrant_client_manager, es_client_manager, meta_mysql_client_manager, dw_mysql_client_manager):
                    manager.init()
                    initialized.append(manager)
                async with asyncio.timeout(15):
                    for manager in (meta_mysql_client_manager, dw_mysql_client_manager):
                        async with manager.session_factory() as session:
                            await session.execute(text("SELECT 1"))
                    if not await es_client_manager.client.ping():
                        raise RuntimeError("SEARCH_SERVICE_UNAVAILABLE")
                    if not await es_client_manager.client.indices.exists(index=app_config.es.index_name):
                        raise RuntimeError("VALUE_INDEX_MISSING")
                    profile = active_profile()
                    for collection in (profile.column_collection, profile.metric_collection):
                        if not await qdrant_client_manager.client.collection_exists(collection):
                            raise RuntimeError("VECTOR_INDEX_MISSING")
                    vector = await embedding_client_manager.client.aembed_query("healthcheck")
                    if len(vector) != app_config.qdrant.embedding_size:
                        raise RuntimeError("EMBEDDING_DIMENSION_MISMATCH")
                app.state.ready = True
            except Exception as error:
                app.state.service_error = type(error).__name__
        yield
    finally:
        for manager in reversed(initialized):
            try:
                await manager.close()
            except Exception:
                pass
