from app.agent.nodes.generate_sql import generate_sql


async def correct_sql(state, runtime):
    # Regenerate the structured plan; never allow the model to repair a fixed
    # business formula by rewriting its SQL directly.
    runtime.stream_writer({"type": "progress", "step": "修正查询计划", "status": "running"})
    result = await generate_sql(state, runtime)
    runtime.stream_writer({"type": "progress", "step": "修正查询计划", "status": "success"})
    return result
