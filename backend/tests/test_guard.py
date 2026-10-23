import pytest

from improved.guard import SQLGuard, QueryRejected


@pytest.fixture
def guard():
    return SQLGuard({"hr_monthly": ["employee_id", "department_id", "month", "end_active"],
                     "departments": ["id", "name"]}, dialect="sqlite", max_rows=5)


@pytest.mark.parametrize("sql", [
    "DELETE FROM hr_monthly", "SELECT 1; DROP TABLE hr_monthly",
    "SELECT * FROM hr_monthly", "SELECT salary FROM payroll",
    "SELECT load_extension('x')", "SELECT randomblob(999999999)",
    "SELECT * FROM sqlite_master", "PRAGMA writable_schema=1",
    "SELECT employee_id FROM hr_monthly -- comment",
    "SELECT employee_id FROM hr_monthly, departments",
    "SELECT employee_id FROM hr_monthly LIMIT -1",
    "WITH RECURSIVE x AS (SELECT 1 UNION ALL SELECT 1 FROM x) SELECT 1 FROM x",
    "SELECT fake_column FROM hr_monthly",
    "SELECT employee_id FROM other.hr_monthly",
])
def test_rejects_unsafe_or_unknown_sql(guard, sql):
    with pytest.raises(QueryRejected):
        guard.validate(sql)


@pytest.mark.parametrize("sql", [
    "SELECT COUNT(*) AS n FROM hr_monthly",
    "SELECT employee_id FROM hr_monthly LIMIT 999",
    "WITH x AS (SELECT employee_id FROM hr_monthly) SELECT employee_id FROM x",
    "SELECT m.employee_id, d.name FROM hr_monthly m JOIN departments d ON m.department_id=d.id",
])
def test_safe_query_is_bounded(guard, sql):
    checked = guard.validate(sql)
    assert "LIMIT 5" in checked


def test_mysql_special_forms_rejected():
    guard = SQLGuard({"t": ["id"]}, dialect="mysql")
    for sql in ["SELECT id FROM t FOR UPDATE", "SELECT id INTO OUTFILE '/tmp/x' FROM t",
                "SELECT SLEEP(1)", "SELECT @@version", "SELECT @a:=1", "SELECT /*!50000 SLEEP(1) */ id FROM t"]:
        with pytest.raises(QueryRejected):
            guard.validate(sql)
