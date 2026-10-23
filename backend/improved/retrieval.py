import asyncio
from pathlib import Path
import yaml
from improved.model_calls import invoke_json
from improved.profiles import active_profile


def query_policy():
    return yaml.safe_load((active_profile().conf / "query_policy.yaml").read_text(encoding="utf-8"))["tables"]


def authorized_field(field):
    parts = field.split(".")
    return len(parts) == 2 and parts[1] in query_policy().get(parts[0], [])


async def expanded_keywords(task, state):
    result = await invoke_json(task, {"query": state["query"]}, "抽取并扩展不超过6个用于检索的词，只返回字符串数组。不要增加问题中没有的筛选条件。")
    if not isinstance(result, list) or any(not isinstance(x, str) for x in result):
        raise ValueError("INVALID_KEYWORD_RESPONSE")
    values = [state["query"], *state.get("keywords", []), *result]
    return list(dict.fromkeys(x.strip()[:200] for x in values if isinstance(x, str) and x.strip()))[:12]


async def bounded_search(values, search):
    limiter = asyncio.Semaphore(4)
    async def one(value):
        async with limiter:
            return await search(value)
    tasks = [asyncio.create_task(one(value)) for value in values]
    try:
        return await asyncio.gather(*tasks)
    finally:
        # gather does not cancel siblings when a child fails. Join all children
        # before releasing the request, including on graph/client cancellation.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
