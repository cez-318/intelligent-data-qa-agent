import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import re
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from improved.guard import SQLGuard, QueryRejected
from improved.profiles import active_profile
from improved.analysis_queries import MAX_ANALYSIS_GROUPS


class DWMySQLRepository:
    """MySQL 8 gate; a separately provisioned SELECT-only account is required."""
    def __init__(self, session: AsyncSession, policy=None):
        self.session = session
        if policy is None:
            path = active_profile().conf / "query_policy.yaml"
            policy = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.guard = SQLGuard(policy["tables"], dialect="mysql", max_rows=policy.get("max_rows", 200))
        self.timeout_ms = int(policy.get("timeout_ms", 3000))
        if not 1 <= self.timeout_ms <= 30000:
            raise ValueError("timeout_ms outside allowed range")

    def _identifier(self, name, table=None):
        permitted = self.guard.schema if table is None else self.guard.schema.get(table, [])
        if name not in permitted or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise QueryRejected("IDENTIFIER_NOT_ALLOWED")
        return f"`{name}`"

    async def get_column_types(self, table_name: str) -> dict[str, str]:
        result = await self.session.execute(text(f"SHOW COLUMNS FROM {self._identifier(table_name)}"))
        return {row.Field: row.Type for row in result.fetchall() if row.Field in self.guard.schema[table_name]}

    async def get_column_values(self, table_name: str, column_name: str, limit: int):
        table = self._identifier(table_name)
        column = self._identifier(column_name, table_name)
        limit = min(max(int(limit), 1), 1000)
        result = await self.session.execute(text(f"SELECT DISTINCT {column} FROM {table} LIMIT :limit"), {"limit": limit})
        return result.scalars().fetchall()

    async def get_db_info(self):
        return {"version": "MySQL 8 (configured target)", "dialect": "mysql", "dataset": active_profile().public_info()}

    async def _prepare(self):
        await self.session.execute(text(f"SET SESSION MAX_EXECUTION_TIME={self.timeout_ms}"))
        await self.session.execute(text("SET SESSION innodb_lock_wait_timeout=3"))

    async def validate_sql(self, sql, params=None):
        checked = self.guard.validate(sql)
        try:
            async with asyncio.timeout(self.timeout_ms / 1000 + 1):
                await self._prepare()
                await self.session.execute(text("EXPLAIN " + checked), params or {})
        except TimeoutError:
            await self.session.invalidate()
            raise QueryRejected("QUERY_TIMEOUT") from None

    async def execute_sql(self, sql, params=None):
        checked = self.guard.validate(sql)
        try:
            async with asyncio.timeout(self.timeout_ms / 1000 + 1):
                await self._prepare()
                result = await self.session.execute(text(checked), params or {})
                return [dict(row) for row in result.mappings().fetchmany(self.guard.max_rows)]
        except TimeoutError:
            await self.session.invalidate()
            raise QueryRejected("QUERY_TIMEOUT") from None

    @asynccontextmanager
    async def consistent_snapshot(self):
        # This dedicated warehouse session is read-only. End EXPLAIN's implicit
        # transaction before establishing one snapshot for totals and all groups.
        await self.session.rollback()
        try:
            await self.session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
            await self.session.execute(text('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY'))
            yield
        finally:
            await self.session.rollback()

    async def validate_analysis_query(self, sql, params=None):
        guard = SQLGuard(self.guard.schema, dialect='mysql', max_rows=MAX_ANALYSIS_GROUPS+1)
        checked = guard.validate(sql)
        try:
            async with asyncio.timeout(self.timeout_ms/1000+1):
                await self._prepare()
                await self.session.execute(text('EXPLAIN '+checked), params or {})
        except TimeoutError:
            await self.session.invalidate()
            raise QueryRejected('QUERY_TIMEOUT') from None

    async def execute_analysis_query(self, sql, params=None):
        # Never called for model-provided detail SQL; queries originate solely in
        # build_analysis_queries after metric/dimension recipe authorization.
        guard = SQLGuard(self.guard.schema, dialect='mysql', max_rows=MAX_ANALYSIS_GROUPS+1)
        checked = guard.validate(sql)
        try:
            async with asyncio.timeout(self.timeout_ms/1000+1):
                await self._prepare()
                result = await self.session.execute(text(checked), params or {})
                rows = [dict(row) for row in result.mappings().fetchmany(MAX_ANALYSIS_GROUPS+1)]
                if len(rows) > MAX_ANALYSIS_GROUPS:
                    raise QueryRejected('ANALYSIS_GROUP_LIMIT_EXCEEDED')
                return rows
        except TimeoutError:
            await self.session.invalidate()
            raise QueryRejected('QUERY_TIMEOUT') from None
