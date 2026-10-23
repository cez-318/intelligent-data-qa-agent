import time
from improved.compiler import QueryPlan, SemanticCompiler
from improved.analysis_queries import build_analysis_queries
from improved.decomposition import segment_contributions, volume_value_decomposition, AnalysisRejected


async def execute_decomposition(state, repository):
    plan = QueryPlan.model_validate(state['query_plan'])
    compiler = SemanticCompiler()
    # Rebuild from registered recipes, rather than trusting a mutable SQL bundle.
    queries = build_analysis_queries(plan, compiler)
    names = {name.casefold():name for name in compiler.rules['metrics']}
    def public(items):
        return [{names.get(k.casefold(),k):v for k,v in row.items() if k.casefold() != '__sample_rows'} for row in items]
    started = time.perf_counter()
    results = {}
    async with repository.consistent_snapshot():
        for query in queries:
            results[query['name']] = public(await repository.execute_analysis_query(query['sql'],query['params']))
    now, old = results['current_total'], results['previous_total']
    evidence = {'mode':'llm_rag', 'query_plan':plan.model_dump(), 'semantic_version':compiler.rules['version'],
                'analysis_version':compiler.rules['analysis']['version'],
                'analysis_queries':queries, 'snapshot':'repeatable_read_read_only',
                'definitions':{m:compiler.rules['metrics'][m]['definition'] for m in plan.metrics},
                'dataset_notice':'仅覆盖已加载历史快照；首尾年份可能不完整，不代表政策因果。', 'possibly_truncated':False}
    output = {'type':'result', 'data':now, 'comparison_data':old, 'analysis':None,
              'evidence':evidence, 'execution_ms':round((time.perf_counter()-started)*1000,2)}
    if not now or not old:
        output.update(summary='至少一期没有符合条件的原始记录，无法做贡献分解，不将整期缺失当成零。',
                      decomposition={'status':'unavailable','causal':False,'reason':'missing_period'})
        return output
    if len(now) != 1 or len(old) != 1:
        raise AnalysisRejected('INVALID_TOTAL_GRAIN')
    if plan.analysis == 'segments':
        metric, dimension = plan.metrics[0], plan.dimensions[0].replace('.','__')
        analysis = segment_contributions(results['current_groups'], results['previous_groups'], dimension,
                                         metric, now[0][metric], old[0][metric], display_limit=min(plan.limit,50))
        output['data'] = [{dimension:r['group'],'current':r['current'],'previous':r['previous'],
                           'difference':r['difference'],'contribution_percent':r['contribution_percent'],
                           'presence':r['presence']} for r in analysis['rows']]
        output['summary'] = f"完整核对 {analysis['group_count']} 个分组，展示绝对变化最大的 {len(analysis['rows'])} 组；其余贡献单列。不是因果解释。"
    else:
        recipe = compiler.rules['analysis']['volume_value']
        if not now[0][recipe['orders']] or not old[0][recipe['orders']]:
            output.update(summary='至少一期有效订单数为零，客单价未定义，不能进行两因素分解。',
                          decomposition={'status':'unavailable','causal':False,'reason':'zero_order_denominator'})
            return output
        analysis = volume_value_decomposition(now[0][recipe['revenue']],now[0][recipe['orders']],old[0][recipe['revenue']],old[0][recipe['orders']])
        output['data'] = [{'factor':'订单数','difference':analysis['order_count_effect'],'contribution_percent':analysis['order_count_contribution_percent']},
                          {'factor':'平均订单金额','difference':analysis['average_order_value_effect'],'contribution_percent':analysis['aov_contribution_percent']}]
        output['summary'] = '销售额变化已按订单数与平均订单金额对称分解；客单价变化不是纯价格效应，也不是政策因果效应。'
    analysis['status'] = 'complete'
    output['decomposition'] = analysis
    return output
