from improved.retrieval import expanded_keywords, bounded_search, authorized_field
from improved.diagnostics import observed_call


async def recall_column(state, runtime):
    runtime.stream_writer({"type": "progress", "step": "召回字段", "status": "running"})
    keywords = await expanded_keywords("expand_columns", state)
    vectors = await observed_call("column_embedding", lambda: runtime.context["embedding_client"].aembed_documents(keywords), retry_read=True, timeout=25)
    batches = await observed_call("column_search", lambda: bounded_search(vectors, runtime.context["column_qdrant_repository"].search), retry_read=True, timeout=12)
    columns = {item.id: item for batch in batches for item in batch if authorized_field(item.id)}
    runtime.stream_writer({"type": "progress", "step": "召回字段", "status": "success"})
    return {"retrieved_columns": list(columns.values())}
