import asyncio
from contextlib import contextmanager, closing
from pathlib import Path
import logging
import sqlite3
import time
import uuid

from improved.guard import SQLGuard
from tests.legacy.semantic import SemanticCatalog, Clarification, previous_month, compare_values
from tests.legacy.workflow import run_validated_query

logger = logging.getLogger("improved.audit")
SCHEMA = {"departments": ["id", "name"], "hr_monthly": ["employee_id", "department_id", "month", "employment_type", "start_active", "end_active", "hires", "exits"]}


def seed_demo(path: Path):
    """Create deterministic fictional records; never replace an existing database."""
    path = Path(path)
    if path.exists():
        raise FileExistsError("Demo database already exists; choose a new path")
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE departments(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
            CREATE TABLE hr_monthly(
                employee_id INTEGER NOT NULL, department_id INTEGER NOT NULL REFERENCES departments(id),
                month TEXT NOT NULL, employment_type TEXT NOT NULL,
                start_active INTEGER CHECK(start_active IN (0,1)), end_active INTEGER CHECK(end_active IN (0,1)),
                hires INTEGER CHECK(hires IN (0,1)), exits INTEGER CHECK(exits IN (0,1)),
                PRIMARY KEY(employee_id, month), CHECK(start_active + hires - exits = end_active));
            CREATE TABLE private_payroll(employee_id INTEGER, salary INTEGER);
            INSERT INTO private_payroll VALUES(1, 99999);
        """)
        conn.executemany("INSERT INTO departments VALUES(?,?)", [(1, "人力部"), (2, "研发部"), (3, "销售部")])
        august = [(1,1,1,1,0,0),(2,1,1,1,0,0),(4,2,1,1,0,0),(5,2,1,1,0,0),(7,3,1,1,0,0),(8,3,0,1,1,0),(9,1,1,1,0,0)]
        september = [(1,1,1,1,0,0),(2,1,1,0,0,1),(3,1,0,1,1,0),(4,2,1,1,0,0),(5,2,1,1,0,0),(6,2,0,1,1,0),(7,3,1,0,0,1),(8,3,1,1,0,0),(9,1,1,1,0,0),(10,3,0,1,1,0)]
        for month, rows in [("2026-08-01", august), ("2026-09-01", september)]:
            conn.executemany("INSERT INTO hr_monthly VALUES(?,?,?,?,?,?,?,?)", [
                (employee, department, month, "实习生" if employee >= 9 else "正式", start, end, hires, exits)
                for employee, department, start, end, hires, exits in rows])


class SQLiteRepository:
    def __init__(self, database: Path, params=None, *, timeout_seconds=2, max_rows=200):
        self.database = Path(database).resolve()
        self.params = params or {}
        self.timeout_seconds = timeout_seconds
        self.guard = SQLGuard(SCHEMA, dialect="sqlite", max_rows=max_rows)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True, timeout=1)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        deadline = time.monotonic() + self.timeout_seconds
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
        try:
            yield connection
        finally:
            connection.close()

    def _validate(self, sql):
        checked = self.guard.validate(sql)
        with self.connect() as connection:
            connection.execute("EXPLAIN QUERY PLAN " + checked, self.params).fetchall()

    async def validate_sql(self, sql):
        await asyncio.to_thread(self._validate, sql)

    def _execute(self, sql):
        # Defense in depth: execution never trusts a previous validation call.
        checked = self.guard.validate(sql)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(checked, self.params).fetchmany(self.guard.max_rows)]

    async def execute_sql(self, sql):
        return await asyncio.to_thread(self._execute, sql)


class DemoService:
    def __init__(self, database):
        self.database = Path(database)
        self.repository = SQLiteRepository(self.database)
        self.catalog = SemanticCatalog()

    async def ask(self, question):
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        try:
            plan = self.catalog.parse(question)
        except Clarification as error:
            return {"type": "clarification", "message": str(error), "request_id": request_id}
        sql, params = self.catalog.build(plan)
        rows = await run_validated_query(SQLiteRepository(self.database, params), sql)
        metric = self.catalog.metrics[plan.metric]
        result = {"type": "result", "data": rows, "request_id": request_id,
                  "summary": f"{plan.month[:7]} {metric['name']}；" + ("无数据，不解释为零。" if not rows else "仅统计正式员工。"),
                  "evidence": {"dataset": self.catalog.config["version"], "mode": "offline_rule_parser",
                               "definition": metric["definition"], "population": self.catalog.config["population"],
                               "sql": self.repository.guard.validate(sql), "parameters": params,
                               "unit": metric["unit"], "month": plan.month, "data_is_synthetic": True}}
        if plan.compare:
            old_month = previous_month(plan.month)
            old_sql, old_params = self.catalog.build(plan, old_month)
            old = await run_validated_query(SQLiteRepository(self.database, old_params), old_sql)
            result["comparison_data"] = old
            result["evidence"]["comparison_month"] = old_month
            if plan.group_by_department:
                old_map = {r["department"]: r["value"] for r in old}
                new_map = {r["department"]: r["value"] for r in rows}
                result["analysis"] = [{"department": dep, **compare_values(new_map.get(dep), old_map.get(dep), is_rate=plan.metric == "turnover")}
                                      for dep in sorted(old_map.keys() | new_map.keys())]
            else:
                result["analysis"] = compare_values(rows[0]["value"] if rows else None, old[0]["value"] if old else None, is_rate=plan.metric == "turnover")
            result["summary"] += " 环比为描述性对比，不代表因果分析。"
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        result["elapsed_ms"] = elapsed
        logger.info("query_completed request_id=%s elapsed_ms=%s row_count=%s", request_id, elapsed, len(rows))
        return result
