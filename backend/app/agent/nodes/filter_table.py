from copy import deepcopy
from improved.model_calls import invoke_json


async def filter_table(state, runtime):
    runtime.stream_writer({"type": "progress", "step": "筛选相关字段", "status": "running"})
    result = await invoke_json("select_columns", {"query": state["query"], "tables": state["table_infos"]},
                               "选择回答问题需要的表和字段。返回 {表名:[字段名]}。不要添加不存在的字段。")
    if not isinstance(result, dict) or any(not isinstance(value, list) for value in result.values()):
        raise ValueError("INVALID_FIELD_SELECTION")
    tables = deepcopy(state["table_infos"])
    tables = [table for table in tables if table["name"] in result]
    for table in tables:
        table["columns"] = [column for column in table["columns"] if column["name"] in result[table["name"]] ]
    runtime.stream_writer({"type": "progress", "step": "筛选相关字段", "status": "success"})
    return {"table_infos": tables}
