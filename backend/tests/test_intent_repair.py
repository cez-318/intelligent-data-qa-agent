import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.agent.nodes.generate_sql import generate_sql


def test_missing_country_repair_is_checked_again_before_execution(monkeypatch):
    monkeypatch.setenv('DATA_AGENT_PROFILE','retail_ii')
    broken = {'mode':'metric','plan':{'metrics':['SALES_AMOUNT'],'filters':[{'field':'dim_date.year','op':'eq','value':2010}]}}
    caller = AsyncMock(return_value=broken)
    monkeypatch.setattr('app.agent.nodes.generate_sql.invoke_json',caller)
    state = {'query':'2010年法国销售额','table_infos':[],'metric_infos':[],'date_info':{},'db_info':{}}
    result = asyncio.run(generate_sql(state,SimpleNamespace(stream_writer=lambda e:None)))
    assert 'clarification' in result and 'sql' not in result
    assert caller.await_count == 2


def test_repair_can_restore_country_without_rule_generating_answer(monkeypatch):
    monkeypatch.setenv('DATA_AGENT_PROFILE','retail_ii')
    broken = {'mode':'metric','plan':{'metrics':['SALES_AMOUNT'],'filters':[]}}
    repaired = {'mode':'metric','plan':{'metrics':['SALES_AMOUNT'],'filters':[{'field':'dim_country.country','op':'eq','value':'France'}]}}
    caller = AsyncMock(side_effect=[broken,repaired])
    monkeypatch.setattr('app.agent.nodes.generate_sql.invoke_json',caller)
    state = {'query':'法国全部历史销售额','table_infos':[],'metric_infos':[],'date_info':{},'db_info':{}}
    result = asyncio.run(generate_sql(state,SimpleNamespace(stream_writer=lambda e:None)))
    assert result['sql_params']['p0'] == 'France'
