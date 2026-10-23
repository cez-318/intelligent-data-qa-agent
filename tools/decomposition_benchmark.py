"""New frozen accounting cases; independent oracle uses raw invoice rows only."""
import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
import os
import sys
import duckdb
from retail_pipeline import ROOT, DATA, digest
from retail_benchmark import oracle_sql, run, matching_rows

BENCH = ROOT / 'backend/evaluation/decomposition_v1.json'


def definitions():
    windows = [
      ({'start':'2011-01-01','end':'2011-04-01'},{'start':'2010-01-01','end':'2010-04-01'},'2011年第一季度相比2010年第一季度'),
      ({'start':'2011-06-01','end':'2011-07-01'},{'start':'2010-06-01','end':'2010-07-01'},'2011年6月相比2010年6月'),
      ({'start':'2011-09-01','end':'2011-10-01'},{'start':'2011-08-01','end':'2011-09-01'},'2011年9月相比2011年8月'),
      ({'start':'2011-11-01','end':'2011-12-01'},{'start':'2010-11-01','end':'2010-12-01'},'2011年11月相比2010年11月')]
    cases = []
    for dimension, label in [('country','国家'),('stock_code','商品代码')]:
        for current,previous,wording in windows:
            cases.append({'family':'segment_'+dimension,'kind':'segments','dimension':dimension,
                          'question':f'{wording}，按{label}分解销售额增减贡献，展示绝对变化最大的前5组并给出其余贡献',
                          'period':current,'baseline':previous,'metrics':['SALES_AMOUNT'],'display_limit':5})
    for country,label in [(None,''),('France','法国')]:
        for current,previous,wording in windows:
            cases.append({'family':'factors','kind':'volume_value','country':country,
                          'question':f'{label}{wording}，将销售额变化分解为订单数和平均订单金额各自的贡献',
                          'period':current,'baseline':previous,'metrics':['SALES_AMOUNT','ORDER_COUNT']})
    current,previous,wording = windows[1]
    cases.extend([
      {'family':'missing_period','kind':'segments','dimension':'country','metrics':['SALES_AMOUNT'],
       'period':current,'baseline':{'start':'2025-06-01','end':'2025-07-01'},'display_limit':5,
       'question':'将2011年6月相比2025年6月的销售额变化按国家做贡献分解；没有整期数据就明确说明，不把缺期算作零','unavailable':'missing_period'},
      {'family':'nonadditive','terminal':'clarification','question':'2011年6月比2010年6月，各商品的去重客户数增长贡献相加是多少？请直接相加计算总体增长'},
      {'family':'causal_boundary','terminal':'clarification','question':'根据2011年6月对2010年6月的订单变化，计算培训政策造成的因果销售增量'},
      {'family':'country_regression','question':'按年月列出2010年法国每个月的销售额','period':{'start':'2010-01-01','end':'2011-01-01'},'metrics':['SALES_AMOUNT'],'country':'France','dimension':'year_month','ordinary':True},
    ])
    for i,case in enumerate(cases):
        case['id'] = f'decomposition-{i+1:02d}'
        case['split'] = 'development' if i in {0,4,8,12,16,19} else 'test'
    return cases


def records(db, case, baseline=False, totals=False):
    scoped = {**case}
    if totals:
        scoped.pop('dimension',None)
    sql,params = oracle_sql(scoped,baseline=baseline)
    cursor = db.execute(sql,params)
    return [dict(zip([c[0] for c in cursor.description],r)) for r in cursor.fetchall()], {'sql':sql,'params':params}


def freeze():
    if BENCH.exists():
        raise RuntimeError('BENCHMARK_ALREADY_FROZEN')
    db = duckdb.connect(str(DATA/'reference.duckdb'),read_only=True)
    cases = definitions()
    for case in cases:
        if case.get('terminal'):
            continue
        now,query = records(db,case,totals=not case.get('ordinary'))
        case['gold_queries'] = [query]
        if case.get('ordinary'):
            case['expected'] = now
            continue
        old,query = records(db,case,baseline=True,totals=True)
        case['gold_queries'].append(query)
        if case.get('unavailable'):
            assert not now or not old
            continue
        r1,r0 = Decimal(str(now[0]['SALES_AMOUNT'])),Decimal(str(old[0]['SALES_AMOUNT']))
        golden = {'current':r1,'previous':r0,'difference':r1-r0}
        if case['kind']=='segments':
            current,query = records(db,case)
            case['gold_queries'].append(query)
            previous,query = records(db,case,baseline=True)
            case['gold_queries'].append(query)
            field = 'dim_country__country' if case['dimension']=='country' else 'dim_product__stock_code'
            first = {r[field]:Decimal(str(r['SALES_AMOUNT'])) for r in current}
            second = {r[field]:Decimal(str(r['SALES_AMOUNT'])) for r in previous}
            golden['groups'] = [{'group':g,'current':first.get(g,0),'previous':second.get(g,0),
                                 'difference':first.get(g,0)-second.get(g,0)} for g in first.keys()|second.keys()]
            golden['groups'].sort(key=lambda r:(-abs(r['difference']),str(r['group'])))
            assert sum(first.values()) == r1 and sum(second.values()) == r0
        else:
            with localcontext() as context:
                context.prec=50
                n1,n0 = Decimal(now[0]['ORDER_COUNT']),Decimal(old[0]['ORDER_COUNT'])
                # Independent two-replacement-path average; no production math import.
                crossed_n = n1*(r0/n0)
                crossed_a = n0*(r1/n1)
                golden['order_count_effect'] = ((crossed_n-r0)+(r1-crossed_a))/2
                golden['average_order_value_effect'] = ((crossed_a-r0)+(r1-crossed_n))/2
        case['gold'] = golden
    db.close()
    payload={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),'limitation':'20 targeted cases, 6 development (includes old country omission regression), 14 held-out instances. Shared templates; not broad business accuracy.',
             'oracle_source':'DuckDB raw_lines; independent SQL and two-replacement arithmetic, not production fact metrics or decomposition functions',
             'cases':cases}
    BENCH.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    BENCH.with_suffix('.sha256').write_text(digest(BENCH)+'\n',encoding='ascii')
    print('Frozen 20 cases: 6 development and 14 held-out.',flush=True)


def close(a,b):
    try:
        first,second=Decimal(str(a)),Decimal(str(b))
        return first.is_finite() and second.is_finite() and abs(first-second)<=Decimal('0.000001')
    except Exception:
        return False


def grade(result,case):
    if case.get('terminal'):
        return result.get('type')==case['terminal']
    if result.get('type')!='result':
        return False
    if case.get('ordinary'):
        return matching_rows(result.get('data'),case['expected'])
    analysis=result.get('decomposition') or {}
    if case.get('unavailable'):
        return analysis.get('status')=='unavailable' and analysis.get('reason')==case['unavailable']
    gold=case['gold']
    if analysis.get('kind')!=case['kind'] or analysis.get('causal') is not False or not close(analysis.get('reconciliation_residual'),0):
        return False
    if not all(close(analysis.get(k),gold[k]) for k in ('current','previous','difference')):
        return False
    if case['kind']=='volume_value':
        return all(close(analysis.get(k),gold[k]) for k in ('order_count_effect','average_order_value_effect'))
    expected=gold['groups'][:case['display_limit']]
    actual=analysis.get('rows',[])
    if analysis.get('group_count')!=len(gold['groups']) or len(actual)!=len(expected):
        return False
    for row,reference in zip(actual,expected):
        if row.get('group')!=reference['group'] or not all(close(row.get(k),reference[k]) for k in ('current','previous','difference')):
            return False
        delta=Decimal(str(gold['difference']))
        if delta and not close(row.get('contribution_percent'),Decimal(str(reference['difference']))/delta*100):
            return False
    remainder=analysis.get('remainder',{})
    return all(close(remainder.get(k),sum(Decimal(str(r[k])) for r in gold['groups'][case['display_limit']:])) for k in ('current','previous','difference'))


def query_plan(case):
    def filters(period):
        result=[{'field':'fact_retail_line.date_id','op':'gte','value':int(period['start'].replace('-',''))},
                {'field':'fact_retail_line.date_id','op':'lt','value':int(period['end'].replace('-',''))}]
        if case.get('country'):
            result.append({'field':'dim_country.country','op':'eq','value':case['country']})
        return result
    dimension={'country':'dim_country.country','stock_code':'dim_product.stock_code'}
    return {'analysis':case['kind'],'metrics':['SALES_AMOUNT'],
            'dimensions':[dimension[case['dimension']]] if case['kind']=='segments' else [],
            'filters':filters(case['period']),'comparison_filters':filters(case['baseline']),
            'limit':case.get('display_limit',10)}


async def direct():
    os.environ['DATA_AGENT_PROFILE']='retail_ii'
    sys.path.insert(0,str(ROOT/'backend'))
    from app.clients.mysql_client_manager import dw_mysql_client_manager
    from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
    from improved.analysis_execution import execute_decomposition
    dw_mysql_client_manager.init()
    outputs=[]
    try:
        async with dw_mysql_client_manager.session_factory() as session:
            repo=DWMySQLRepository(session)
            for case in json.loads(BENCH.read_text(encoding='utf-8'))['cases']:
                if case.get('terminal') or case.get('ordinary'):
                    continue
                result=await execute_decomposition({'query_plan':query_plan(case)},repo)
                passed=grade(result,case)
                outputs.append({'id':case['id'],'passed':passed,'result':result})
                print(json.dumps({'id':case['id'],'passed':passed}),flush=True)
    finally:
        await dw_mysql_client_manager.close()
    path=ROOT/'reports'/'decomposition_direct.json'
    path.write_text(json.dumps({'controlled_plan':True,'live_mysql':True,'cases':outputs},ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    if not all(o['passed'] for o in outputs):
        raise RuntimeError('DIRECT_SQL_OR_MATH_MISMATCH')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['freeze','direct','run'])
    parser.add_argument('--split',choices=['development','test','all'],default='development')
    parser.add_argument('--workers',type=int,choices=[1,2],default=1)
    parser.add_argument('--port',type=int,default=8000)
    parser.add_argument('--offset',type=int,default=0)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--ids',nargs='+')
    parser.add_argument('--confirm-paid-llm-evaluation',action='store_true')
    args=parser.parse_args()
    if args.action=='freeze':
        freeze()
    elif args.action=='direct':
        asyncio.run(direct())
    else:
        if not args.confirm_paid_llm_evaluation:
            parser.error('Use --confirm-paid-llm-evaluation for actual API calls')
        run(args,benchmark_path=BENCH,checker=grade,report_prefix='decomposition_live')
