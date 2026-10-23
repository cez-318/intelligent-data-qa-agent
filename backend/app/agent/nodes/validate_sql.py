from improved.guard import QueryRejected


async def validate_sql(state, runtime):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "校验SQL", "status": "running"})
    attempts = state.get("validation_attempts", 0) + 1
    try:
        repository = runtime.context["dw_mysql_repository"]
        if state.get('analysis_queries'):
            for query in state['analysis_queries']:
                await repository.validate_analysis_query(query['sql'],query['params'])
            writer({"type": "progress", "step": "校验SQL", "status": "success"})
            return {"error": None, "validation_attempts": attempts, "terminal_error": False}
        if state.get("sql_params"):
            await repository.validate_sql(state["sql"], state["sql_params"])
        else:
            await repository.validate_sql(state["sql"])
        if state.get("comparison_sql"):
            await repository.validate_sql(state["comparison_sql"], state.get("comparison_params", {}))
    except Exception as error:
        writer({"type": "progress", "step": "校验SQL", "status": "error"})
        terminal = isinstance(error, QueryRejected) and not error.retryable
        return {"error": "SQL_VALIDATION_FAILED", "validation_attempts": attempts, "terminal_error": terminal}
    writer({"type": "progress", "step": "校验SQL", "status": "success"})
    return {"error": None, "validation_attempts": attempts, "terminal_error": False}


def validation_route(state):
    if state.get("error") is None:
        return "execute_sql"
    if state.get("terminal_error") or state.get("validation_attempts", 0) >= 3:
        return "reject_sql"
    return "correct_sql"


async def reject_sql(state, runtime):
    runtime.stream_writer({"type": "error", "message": "查询未通过安全或有效性校验，已停止执行。请调整问题或联系维护者。"})
    return {}
