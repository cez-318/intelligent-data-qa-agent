"""Test-only adapters. The production application must never import this module."""
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import yaml
from langchain_core.messages import AIMessage
from app.entities.column_info import ColumnInfo
from app.entities.table_info import TableInfo
from app.entities.metric_info import MetricInfo
from improved.guard import SQLGuard

CONF = Path(__file__).resolve().parents[2] / "conf"


class Warehouse:
    def __init__(self, path):
        self.path = path
        self.guard = SQLGuard(yaml.safe_load((CONF / "query_policy.yaml").read_text(encoding="utf-8"))["tables"], dialect="sqlite")
        self.executions = 0
        self.fail_validation_once = False
        self.validations = 0
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.executescript("""
                CREATE TABLE dim_region(region_id INTEGER PRIMARY KEY, province TEXT, region_name TEXT, country TEXT);
                CREATE TABLE dim_product(product_id INTEGER PRIMARY KEY, product_name TEXT, category TEXT, brand TEXT);
                CREATE TABLE dim_customer(customer_id INTEGER PRIMARY KEY, member_level TEXT);
                CREATE TABLE dim_date(date_id INTEGER PRIMARY KEY, year INTEGER, quarter INTEGER, month INTEGER, day INTEGER);
                CREATE TABLE fact_order(order_id INTEGER PRIMARY KEY, customer_id INTEGER, product_id INTEGER, date_id INTEGER, region_id INTEGER, order_quantity INTEGER, order_amount REAL);
                INSERT INTO dim_region VALUES (1,'广东','华南','中国'),(2,'北京','华北','中国');
                INSERT INTO dim_product VALUES (1,'虚构电脑','数码','示例A'),(2,'虚构图书','图书','示例B');
                INSERT INTO dim_customer VALUES (1,'金卡');
                INSERT INTO dim_date VALUES (20250101,2025,1,1,1),(20260101,2026,1,1,1);
                INSERT INTO fact_order VALUES (1,1,1,20260101,1,1,100),(2,1,2,20260101,1,2,300),(3,1,1,20260101,2,1,200),(4,1,1,20250101,1,1,100),(5,1,2,20250101,2,1,100);
            """)

    async def get_db_info(self):
        return {"dialect": "sqlite", "version": "test fixture only"}

    async def validate_sql(self, sql, params=None):
        self.validations += 1
        if self.fail_validation_once:
            self.fail_validation_once = False
            raise ValueError("test transient validation error")
        checked = self.guard.validate(sql)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("EXPLAIN QUERY PLAN " + checked, params or {}).fetchall()

    async def execute_sql(self, sql, params=None):
        self.executions += 1
        checked = self.guard.validate(sql)
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("PRAGMA query_only=ON")
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(checked, params or {}).fetchmany(self.guard.max_rows)]


class Metadata:
    def __init__(self):
        config = yaml.safe_load((CONF / "meta_config.yaml").read_text(encoding="utf-8"))
        self.columns, self.tables, self.metrics = {}, {}, []
        for table in config["tables"]:
            self.tables[table["name"]] = TableInfo(table["name"], table["name"], table["role"], table["description"])
            for column in table["columns"]:
                key = table["name"] + "." + column["name"]
                self.columns[key] = ColumnInfo(key, column["name"], "TEXT", column["role"], [], column["description"], column["alias"], table["name"])
        for metric in config["metrics"]:
            self.metrics.append(MetricInfo(metric["name"], metric["name"], metric["description"], metric["relevant_columns"], metric["alias"]))

    async def get_column_info_by_id(self, key):
        return deepcopy(self.columns.get(key))

    async def get_table_info_by_id(self, key):
        return deepcopy(self.tables.get(key))

    async def get_key_columns_by_table_id(self, table):
        return [deepcopy(c) for c in self.columns.values() if c.table_id == table and c.role in {"primary_key", "foreign_key"}]


class Retriever:
    def __init__(self, data):
        self.data, self.calls = data, 0
    async def search(self, _):
        self.calls += 1
        return deepcopy(self.data)


class Embedding:
    async def aembed_documents(self, words):
        return [[1.0, 0.0] for _ in words]


class ScriptedModel:
    """Controlled provider responses, NOT keyword matching in production."""
    def __init__(self, decision):
        self.decision, self.calls = decision, []
    async def ainvoke(self, messages, config=None):
        task = messages[0].content.splitlines()[0].removeprefix("TASK:")
        self.calls.append(task)
        payload = json.loads(messages[1].content)
        if task.startswith("expand_"):
            result = ["统计", "订单"]
        elif task == "select_columns":
            result = {table["name"]: [column["name"] for column in table["columns"]] for table in payload["tables"]}
        elif task == "select_metrics":
            result = [metric["name"] for metric in payload["metrics"]]
        elif task == "plan_query":
            result = self.decision
        else:
            raise AssertionError(f"Unexpected model task: {task}")
        return AIMessage(content=json.dumps(result, ensure_ascii=False))
