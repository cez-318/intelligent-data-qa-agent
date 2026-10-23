"""Actual LangGraph execution with original gate nodes and a real SQLite database.

The model is a controlled test double. This is not a live model evaluation.
"""
import asyncio
import importlib
import sys
from types import SimpleNamespace
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableLambda

from app.agent.nodes.validate_sql import validate_sql, validation_route, reject_sql
from tests.legacy.demo import SQLiteRepository, seed_demo


def test_original_graph_compiles_without_calling_external_services(monkeypatch):
    module = importlib.import_module("app.agent.graph")
    edges = [(edge.source, edge.target) for edge in module.graph.get_graph().edges]
    assert ("correct_sql", "validate_sql") in edges
    assert ("correct_sql", "execute_sql") not in edges
    assert ("reject_sql", "__end__") in edges


class State(TypedDict):
    sql: str
    error: str | None
    terminal_error: bool
    validation_attempts: int
    rows: list


def test_langgraph_repair_loop_with_real_sample_database(tmp_path):
    database = tmp_path / "graph.sqlite3"
    seed_demo(database)
    repo = SQLiteRepository(database)
    builder = StateGraph(State)
    builder.add_node("validate_sql", validate_sql)
    builder.add_node("correct_sql", lambda state: {"sql": "SELECT COUNT(*) AS n FROM hr_monthly"})
    async def execute(state):
        return {"rows": await repo.execute_sql(state["sql"])}
    builder.add_node("execute_sql", execute)
    builder.add_node("reject_sql", reject_sql)
    builder.add_edge(START, "validate_sql")
    builder.add_conditional_edges("validate_sql", validation_route,
                                  {key: key for key in ["correct_sql", "execute_sql", "reject_sql"]})
    builder.add_edge("correct_sql", "validate_sql")
    builder.add_edge("execute_sql", END)
    builder.add_edge("reject_sql", END)
    graph = builder.compile()
    result = asyncio.run(graph.ainvoke({"sql": "SELECT unknown FROM hr_monthly"}, context={"dw_mysql_repository": repo}))
    assert result["validation_attempts"] == 2
    assert result["rows"] == [{"n": 17}]
    rejected = asyncio.run(graph.ainvoke({"sql": "DELETE FROM hr_monthly"}, context={"dw_mysql_repository": repo}))
    assert rejected["validation_attempts"] == 1
    assert "rows" not in rejected
