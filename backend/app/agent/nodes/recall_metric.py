from improved.retrieval import expanded_keywords, bounded_search, authorized_field
from improved.diagnostics import observed_call


async def recall_metric(state, runtime):
    runtime.stream_writer({"type": "progress", "step": "召回指标", "status": "running"})
    keywords = await expanded_keywords("expand_metrics", state)
    vectors = await observed_call("metric_embedding", lambda: runtime.context["embedding_client"].aembed_documents(keywords), retry_read=True, timeout=25)
    batches = await observed_call("metric_search", lambda: bounded_search(vectors, runtime.context["metric_qdrant_repository"].search), retry_read=True, timeout=12)
    metrics = {item.id: item for batch in batches for item in batch if all(authorized_field(field) for field in item.relevant_columns)}
    runtime.stream_writer({"type": "progress", "step": "召回指标", "status": "success"})
    return {"retrieved_metrics": list(metrics.values())}
