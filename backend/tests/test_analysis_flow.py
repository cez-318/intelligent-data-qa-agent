import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2] / 'tools'))
import duckdb
import pytest
from improved.compiler import QueryPlan, SemanticCompiler, PlanRejected
from improved.analysis_queries import build_analysis_queries, MAX_ANALYSIS_GROUPS
from improved.analysis_execution import execute_decomposition
from improved.guard import SQLGuard, QueryRejected
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository


def plan(**overrides):
    return QueryPlan.model_validate({'analysis':'segments','metrics':['SALES_AMOUNT'], 'dimensions':['dim_country.country'],
        'filters':[{'field':'dim_date.year','op':'eq','value':2011}],
        'comparison_filters':[{'field':'dim_date.year','op':'eq','value':2010}], 'limit':2, **overrides})


@pytest.fixture
def retail(monkeypatch):
    monkeypatch.setenv('DATA_AGENT_PROFILE','retail_ii')
    return SemanticCompiler()


@pytest.mark.parametrize('overrides', [
    {'metrics':['AOV']}, {'metrics':['ORDER_COUNT']}, {'metrics':['ACTIVE_CUSTOMERS']},
    {'metrics':['SALES_AMOUNT','UNITS']}, {'dimensions':['dim_product.product_name']},
    {'comparison_filters':None}, {'comparison_filters':[{'field':'dim_country.country','op':'eq','value':'France'}]},
    {'analysis':'volume_value','dimensions':['dim_country.country']},
    {'analysis':'volume_value','dimensions':[],'metrics':['UNITS']},
])
def test_unapproved_analysis_is_rejected(retail, overrides):
    with pytest.raises(PlanRejected):
        build_analysis_queries(plan(**overrides),retail)


def test_only_complete_server_groups_have_larger_cap(retail):
    queries = build_analysis_queries(plan(),retail)
    assert len(queries) == 4
    assert queries[0]['sql'].endswith('LIMIT 10001')
    assert queries[1]['sql'].endswith('LIMIT 1')
    assert retail.compile(plan()).sql.endswith('LIMIT 2')
    assert len(build_analysis_queries(plan(analysis='volume_value',dimensions=[]),retail)) == 2


class AnalysisWarehouse:
    def __init__(self, compiler):
        from retail_pipeline import RAW_DDL, build_warehouse
        self.db = duckdb.connect()
        self.db.execute(RAW_DDL)
        self.db.execute("""INSERT INTO raw_lines VALUES
          (1,'x',2,'1','a','A',1,'2010-01-01',100,'123','France'),
          (2,'x',3,'2','b','B',1,'2010-01-01',100,'124','Germany'),
          (3,'x',4,'3','a','A',1,'2011-01-01',150,'123','France'),
          (4,'x',5,'4','b','B',1,'2011-01-01',100,'124','Germany'),
          (5,'x',6,'5','c','C',1,'2011-01-01',50,'125','Spain')""")
        build_warehouse(self.db)
        self.guard = SQLGuard(compiler.policy['tables'])
        self.calls = 0
        self.snapshots = 0

    @asynccontextmanager
    async def consistent_snapshot(self):
        self.snapshots += 1
        yield

    async def get_db_info(self):
        return {'dialect':'mysql','version':'controlled test'}

    async def validate_analysis_query(self, sql, params):
        SQLGuard(self.guard.schema, max_rows=10001).validate(sql)

    async def execute_analysis_query(self, sql, params):
        self.calls += 1
        sql = re.sub(r':(p\d+(?:_\d+)?)\b',r'$\1',sql)
        cursor = self.db.execute(sql,params)
        return [dict(zip([c[0] for c in cursor.description],r)) for r in cursor.fetchall()]


@pytest.mark.parametrize('kind',['segments','volume_value'])
def test_actual_sql_execution_and_reconciliation(retail,kind):
    warehouse = AnalysisWarehouse(retail)
    query_plan = plan(analysis=kind,dimensions=[] if kind=='volume_value' else ['dim_country.country'])
    result = asyncio.run(execute_decomposition({'query_plan':query_plan.model_dump()},warehouse))
    assert result['decomposition']['difference'] == 100
    assert result['decomposition']['reconciliation_residual'] == 0
    assert warehouse.snapshots == 1
    assert warehouse.calls == (4 if kind=='segments' else 2)


def test_missing_period_never_becomes_zero(retail):
    warehouse = AnalysisWarehouse(retail)
    query_plan = plan(comparison_filters=[{'field':'dim_date.year','op':'eq','value':2025}])
    result = asyncio.run(execute_decomposition({'query_plan':query_plan.model_dump()},warehouse))
    assert result['decomposition']['status'] == 'unavailable'
    assert result['decomposition']['reason'] == 'missing_period'


def test_zero_qualifying_orders_do_not_create_aov(retail):
    warehouse = AnalysisWarehouse(retail)
    warehouse.db.execute('UPDATE fact_retail_line SET sale_invoice = NULL, sale_amount = 0')
    query_plan = plan(analysis='volume_value',dimensions=[])
    result = asyncio.run(execute_decomposition({'query_plan':query_plan.model_dump()},warehouse))
    assert result['decomposition']['reason'] == 'zero_order_denominator'


def test_unexpected_multiple_totals_are_rejected(retail):
    from improved.decomposition import AnalysisRejected
    warehouse = AnalysisWarehouse(retail)
    warehouse.execute_analysis_query = AsyncMock(return_value=[{'SALES_AMOUNT':1},{'SALES_AMOUNT':2}])
    with pytest.raises(AnalysisRejected,match='INVALID_TOTAL_GRAIN'):
        asyncio.run(execute_decomposition({'query_plan':plan().model_dump()},warehouse))


def test_full_original_graph_emits_decomposition(retail,monkeypatch):
    import tests.support.ecommerce as support
    from app.services.query_service import QueryService
    monkeypatch.setattr(support,'CONF',retail.conf)
    metadata = support.Metadata()
    warehouse = AnalysisWarehouse(retail)
    model = support.ScriptedModel({'mode':'metric','plan':plan().model_dump()})
    monkeypatch.setattr('app.agent.llm.get_model', lambda:model)
    service = QueryService(support.Embedding(),support.Retriever(list(metadata.columns.values())),support.Retriever([]),support.Retriever(metadata.metrics),metadata,warehouse)
    async def collect():
        return [json.loads(c[6:]) async for c in service.query('2011年相比2010年按国家分解销售额变化贡献')]
    events = asyncio.run(collect())
    result = next(e for e in events if e['type']=='result')
    assert result['decomposition']['difference'] == '100.000000'
    assert result['decomposition']['causal'] is False


def test_cap_detects_truncation_and_does_not_increase_normal_limit():
    result = MagicMock()
    result.mappings.return_value.fetchmany.return_value = [{'id':i} for i in range(MAX_ANALYSIS_GROUPS+1)]
    session = SimpleNamespace(execute=AsyncMock(return_value=result),invalidate=AsyncMock())
    repo = DWMySQLRepository(session,{'tables':{'t':['id']},'max_rows':200})
    with pytest.raises(QueryRejected,match='ANALYSIS_GROUP_LIMIT'):
        asyncio.run(repo.execute_analysis_query('SELECT id FROM t'))
    assert repo.guard.max_rows == 200


def test_snapshot_rolls_back_even_when_calculation_fails():
    session = SimpleNamespace(execute=AsyncMock(),rollback=AsyncMock())
    repo = DWMySQLRepository(session,{'tables':{'t':['id']}})
    async def execute():
        async with repo.consistent_snapshot():
            raise ValueError('test')
    with pytest.raises(ValueError):
        asyncio.run(execute())
    assert session.rollback.await_count == 2
    assert 'READ ONLY' in str(session.execute.call_args_list[-1].args[0])
