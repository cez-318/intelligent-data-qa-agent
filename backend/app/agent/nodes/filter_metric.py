from copy import deepcopy
from improved.model_calls import invoke_json


async def filter_metric(state, runtime):
    runtime.stream_writer({"type": "progress", "step": "筛选指标", "status": "running"})
    result = await invoke_json("select_metrics", {"query": state["query"], "metrics": state["metric_infos"]},
                               "选出相关指标名称，只返回字符串数组。不相关则返回空数组。")
    if not isinstance(result, list) or any(not isinstance(value, str) for value in result):
        raise ValueError("INVALID_METRIC_SELECTION")
    runtime.stream_writer({"type": "progress", "step": "筛选指标", "status": "success"})
    return {"metric_infos": [deepcopy(metric) for metric in state["metric_infos"] if metric["name"] in result]}
