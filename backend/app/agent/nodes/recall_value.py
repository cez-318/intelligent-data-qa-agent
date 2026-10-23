from improved.retrieval import expanded_keywords, bounded_search, authorized_field
from improved.diagnostics import observed_call


async def recall_value(state, runtime):
    runtime.stream_writer({"type": "progress", "step": "召回字段取值", "status": "running"})
    keywords = await expanded_keywords("expand_values", state)
    batches = await observed_call("value_search", lambda: bounded_search(keywords, runtime.context["value_es_repository"].search), retry_read=True, timeout=12)
    values = {item.id: item for batch in batches for item in batch if authorized_field(item.column_id)}
    runtime.stream_writer({"type": "progress", "step": "召回字段取值", "status": "success"})
    return {"retrieved_values": list(values.values())}
