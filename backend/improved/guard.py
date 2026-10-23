"""Conservative SQL policy. This supplements, never replaces, database privileges."""
from dataclasses import dataclass
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope


class QueryRejected(ValueError):
    retryable = False


class SchemaRejected(QueryRejected):
    retryable = True


@dataclass
class SQLGuard:
    schema: dict[str, list[str]]
    dialect: str = "mysql"
    max_rows: int = 200
    max_sql_length: int = 20000

    def validate(self, sql: str) -> str:
        if not isinstance(sql, str) or not sql.strip() or len(sql) > self.max_sql_length:
            raise QueryRejected("SQL_EMPTY_OR_TOO_LONG")
        # Deliberately conservative: also rejects comment-looking text inside literals.
        if any(marker in sql for marker in ("--", "/*", "*/", "#", "```")):
            raise QueryRejected("SQL_COMMENTS_NOT_ALLOWED")
        try:
            statements = sqlglot.parse(sql, read=self.dialect)
        except SqlglotError:
            raise SchemaRejected("SQL_PARSE_ERROR") from None
        if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union)):
            raise QueryRejected("ONLY_ONE_READ_QUERY_ALLOWED")
        tree = statements[0]
        prohibited = {"Insert", "Update", "Delete", "Create", "Drop", "Alter", "Command",
                      "Into", "Lock", "Transaction", "Commit", "Rollback", "Parameter",
                      "SessionParameter", "PropertyEQ", "Hint", "Use", "Attach", "Pragma"}
        safe_functions = {"COUNT", "SUM", "AVG", "MIN", "MAX", "ROUND", "COALESCE", "NULLIF",
                          "CAST", "CASE", "IF", "ABS", "LOWER", "UPPER", "DATE", "YEAR",
                          "MONTH", "DAY", "TIME_TO_STR", "STR_TO_TIME", "CURRENT_DATE",
                          "DATE_ADD", "DATE_SUB", "DATEDIFF", "DATE_DIFF", "AND", "OR"}
        for node in tree.walk():
            if type(node).__name__ in prohibited:
                raise QueryRejected("SQL_OPERATION_NOT_ALLOWED")
            if isinstance(node, exp.With) and node.args.get("recursive"):
                raise QueryRejected("RECURSION_NOT_ALLOWED")
            if isinstance(node, exp.Table) and (node.db or node.catalog):
                raise QueryRejected("CROSS_DATABASE_NOT_ALLOWED")
            if isinstance(node, exp.Func) and node.sql_name() not in safe_functions:
                raise QueryRejected("SQL_FUNCTION_NOT_ALLOWED")
            if isinstance(node, exp.Star) and not isinstance(node.parent, exp.Count):
                raise QueryRejected("EXPLICIT_COLUMNS_REQUIRED")
            if isinstance(node, exp.Join):
                if node.kind == "CROSS" or not (node.args.get("on") or node.args.get("using")):
                    raise QueryRejected("EXPLICIT_JOIN_REQUIRED")
        for scope in traverse_scope(tree):
            for source in scope.sources.values():
                if isinstance(source, exp.Table) and source.name not in self.schema:
                    raise QueryRejected("TABLE_NOT_ALLOWED")
        schema = {table: {col: "UNKNOWN" for col in columns} for table, columns in self.schema.items()}
        try:
            tree = qualify(tree, dialect=self.dialect, schema=schema,
                           validate_qualify_columns=True, identify=False)
        except SqlglotError:
            raise SchemaRejected("UNKNOWN_OR_AMBIGUOUS_COLUMN") from None
        for offset in tree.find_all(exp.Offset):
            if not re.fullmatch(r"\d+", str(offset.expression)) or int(str(offset.expression)) > self.max_rows * 10:
                raise QueryRejected("OFFSET_OUT_OF_RANGE")
        limit = tree.args.get("limit")
        requested = self.max_rows
        if limit:
            if not re.fullmatch(r"\d+", str(limit.expression)):
                raise QueryRejected("INVALID_LIMIT")
            requested = min(int(str(limit.expression)), self.max_rows)
        tree = tree.limit(requested)
        return tree.sql(dialect=self.dialect)
