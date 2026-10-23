"""Small reusable execution contract; repairs must cross the same validation gate."""
from improved.guard import QueryRejected


async def run_validated_query(repository, sql, repair=None, max_attempts=3):
    if not 1 <= max_attempts <= 3:
        raise ValueError("max_attempts must be between 1 and 3")
    for attempt in range(1, max_attempts + 1):
        try:
            await repository.validate_sql(sql)
        except Exception as error:
            if isinstance(error, QueryRejected) and not error.retryable:
                raise
            if repair is None or attempt == max_attempts:
                raise
            # No database exception text or row values sent to the model.
            sql = await repair(sql, "SQL_VALIDATION_FAILED", attempt)
            continue
        return await repository.execute_sql(sql)
