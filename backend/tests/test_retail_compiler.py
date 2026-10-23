from pathlib import Path
from decimal import Decimal
import sys
import duckdb
import pytest
from improved.compiler import SemanticCompiler, QueryPlan

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from retail_pipeline import RAW_DDL, build_warehouse


@pytest.mark.parametrize('metric,expected', [
    ('SALES_AMOUNT', Decimal('30')), ('ORDER_COUNT', 1), ('AOV', 30),
    ('UNITS', 3), ('ACTIVE_CUSTOMERS', 1), ('CANCEL_AMOUNT', Decimal('10')),
    ('CANCEL_INVOICE_COUNT', 1), ('LINE_COUNT', 3),
])
def test_registered_retail_metric_runs_and_preserves_grain(monkeypatch, metric, expected):
    monkeypatch.setenv('DATA_AGENT_PROFILE', 'retail_ii')
    db = duckdb.connect()
    db.execute(RAW_DDL)
    db.execute("""INSERT INTO raw_lines VALUES
      (1,'test',2,'100','a','A',2,'2011-01-01',10,'123','France'),
      (2,'test',3,'100','b','B',1,'2011-01-01',10,NULL,'France'),
      (3,'test',4,'C101','a','A',-1,'2011-01-01',10,'123','France')""")
    build_warehouse(db)
    compiled = SemanticCompiler().compile(QueryPlan(metrics=[metric], dimensions=['dim_country.country']))
    actual = db.execute(compiled.sql).fetchone()
    assert actual == (expected, 'France', 3)
    assert compiled.version == 'uci_retail_ii_v1'
    db.close()


def test_fixture_field_not_authorized_in_retail(monkeypatch):
    monkeypatch.setenv('DATA_AGENT_PROFILE', 'retail_ii')
    from improved.guard import SQLGuard, QueryRejected
    compiler = SemanticCompiler()
    with pytest.raises(QueryRejected):
        SQLGuard(compiler.policy['tables']).validate('SELECT order_amount FROM fact_order')
