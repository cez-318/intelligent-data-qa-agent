"""Independent raw-source SQL oracle and opt-in end-to-end HTTP evaluation.

The oracle never imports the app's compiler, warehouse columns or metric YAML.
Only the natural-language question is sent to the application, not gold SQL.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import random
from pathlib import Path
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import duckdb
import httpx
from retail_pipeline import DATA, ROOT, digest

BENCH = ROOT / 'backend' / 'evaluation' / 'retail_ii_200.json'
SALE = "invoice_no IS NOT NULL AND upper(invoice_no) NOT LIKE 'C%' AND quantity>0 AND unit_price>0"
CANCEL = "upper(invoice_no) LIKE 'C%' AND quantity<0 AND unit_price>0"
FORMULAS = {
    'SALES_AMOUNT': (f'SUM(CASE WHEN {SALE} THEN quantity*unit_price ELSE 0 END)', '销售额'),
    'ORDER_COUNT': (f'COUNT(DISTINCT CASE WHEN {SALE} THEN invoice_no END)', '去重订单数'),
    'AOV': (f'SUM(CASE WHEN {SALE} THEN quantity*unit_price ELSE 0 END)/NULLIF(COUNT(DISTINCT CASE WHEN {SALE} THEN invoice_no END),0)', '平均订单金额'),
    'UNITS': (f'SUM(CASE WHEN {SALE} THEN quantity ELSE 0 END)', '销量'),
    'ACTIVE_CUSTOMERS': (f'COUNT(DISTINCT CASE WHEN {SALE} THEN customer_id END)', '有客户编号的活跃购买客户数'),
    'CANCEL_AMOUNT': (f'SUM(CASE WHEN {CANCEL} THEN -quantity*unit_price ELSE 0 END)', '取消金额'),
    'CANCEL_INVOICE_COUNT': (f'COUNT(DISTINCT CASE WHEN {CANCEL} THEN invoice_no END)', '取消发票数'),
    'LINE_COUNT': ('COUNT(*)', '原始明细条数'),
}
COUNTRIES = [('United Kingdom', '英国'), ('France', '法国'), ('Germany', '德国'), ('Spain', '西班牙'), ('Netherlands', '荷兰')]


def month_period(index):
    year, month = 2010 + index // 12, index % 12 + 1
    next_year, next_month = (year+1, 1) if month == 12 else (year, month+1)
    return {'start': f'{year}-{month:02d}-01', 'end': f'{next_year}-{next_month:02d}-01', 'label': f'{year}年{month}月'}


def oracle_sql(case, baseline=False):
    period = case['baseline'] if baseline else case['period']
    expressions = [FORMULAS[m][0] + ' AS ' + m for m in case['metrics']]
    dimension = case.get('dimension')
    dims = {'country': ('country', 'dim_country__country'),
            'stock_code': ('stock_code', 'dim_product__stock_code'),
            'year_month': ("strftime(invoice_ts,'%Y-%m')", 'dim_date__year_month')}
    if dimension:
        field, alias = dims[dimension]
        expressions.append(f'{field} AS {alias}')
    sql = 'SELECT ' + ','.join(expressions) + ' FROM raw_lines WHERE invoice_ts >= ? AND invoice_ts < ?'
    params = [period['start'], period['end']]
    if case.get('country'):
        sql += ' AND country = ?'
        params.append(case['country'])
    if dimension:
        sql += ' GROUP BY ' + dims[dimension][0]
    sql += ' HAVING COUNT(*)>0'
    if case.get('top'):
        sql += ' ORDER BY ' + case['metrics'][0] + ' DESC,' + dims[dimension][0] + ' ASC LIMIT ' + str(case['top'])
    return sql, params


def cases():
    output = []
    for index in range(24):
        for offset, metric in enumerate(['SALES_AMOUNT', 'ORDER_COUNT', 'AOV', 'UNITS', 'ACTIVE_CUSTOMERS']):
            country, label = COUNTRIES[(index+offset) % len(COUNTRIES)] if index % 2 else (None, '')
            period = month_period(index)
            output.append({'family': 'monthly_scalar', 'question': f"{period['label']}{label}的{FORMULAS[metric][1]}是多少？", 'period': period, 'country': country, 'metrics': [metric]})
    for index in range(10):
        period = month_period(index+7)
        for metric in ['SALES_AMOUNT', 'CANCEL_AMOUNT']:
            output.append({'family': 'country_group', 'question': f"按国家分别统计{period['label']}的{FORMULAS[metric][1]}", 'period': period, 'metrics': [metric], 'dimension': 'country'})
        output.append({'family': 'product_top10', 'question': f"{period['label']}按商品代码分组，销售额最高的前10个商品代码及其销售额", 'period': period, 'metrics': ['SALES_AMOUNT'], 'dimension': 'stock_code', 'top': 10})
        country, label = COUNTRIES[index % 5]
        year = 2010 + index // 5
        period_year = {'start': f'{year}-01-01', 'end': f'{year+1}-01-01', 'label': f'{year}年'}
        output.append({'family': 'monthly_trend', 'question': f"按年月列出{year}年{label}每个月的销售额", 'period': period_year, 'country': country, 'metrics': ['SALES_AMOUNT'], 'dimension': 'year_month'})
    for index in range(20):
        period = month_period(index)
        metrics = ['SALES_AMOUNT', 'ORDER_COUNT'] if index % 2 else ['LINE_COUNT', 'CANCEL_INVOICE_COUNT']
        output.append({'family': 'multiple_metrics', 'question': f"统计{period['label']}的" + '和'.join(FORMULAS[m][1] for m in metrics), 'period': period, 'metrics': metrics})
    for country, label in COUNTRIES:
        for metric in ['SALES_AMOUNT', 'AOV']:
            output.append({'family': 'comparison', 'question': f"{label}2011年11月的{FORMULAS[metric][1]}相比2010年11月变化多少？", 'period': month_period(22), 'baseline': month_period(10), 'country': country, 'metrics': [metric]})
    for metric in ['SALES_AMOUNT', 'ORDER_COUNT', 'AOV']:
        output.append({'family': 'no_data', 'question': f"统计2025年1月的{FORMULAS[metric][1]}", 'period': {'start': '2025-01-01', 'end': '2025-02-01'}, 'metrics': [metric]})
    for question in ['2011年的净利润是多少？', '按员工部门统计2011年的离职率', '2010年的商品采购成本是多少？',
                     '2011年各品牌的销售额分别是多少？', '证明2011年销售增长是培训政策造成的',
                     '计算2011年人力部门员工满意度', '2011年11月广告投放的因果增量收益是多少？']:
        output.append({'family': 'unsupported', 'question': question, 'terminal': 'clarification'})
    assert len(output) == 200 and len({c['question'] for c in output}) == 200
    dev_ids = set(random.Random(20260927).sample(range(200), 50))
    for index, case in enumerate(output):
        case.update(id=f'retail-{index+1:03d}', split='development' if index in dev_ids else 'test')
    return output


def freeze():
    if BENCH.exists():
        raise RuntimeError('BENCHMARK_ALREADY_FROZEN_NO_OVERWRITE')
    db = duckdb.connect(str(DATA / 'reference.duckdb'), read_only=True)
    output = cases()
    for index, case in enumerate(output):
        if case.get('terminal'):
            continue
        sql, params = oracle_sql(case)
        cursor = db.execute(sql, params)
        case['gold_sql'], case['gold_params'] = sql, params
        case['expected'] = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
        if 'baseline' in case:
            sql, params = oracle_sql(case, baseline=True)
            cursor = db.execute(sql, params)
            case['gold_baseline_sql'], case['gold_baseline_params'] = sql, params
            case['comparison'] = [dict(zip([c[0] for c in cursor.description], row)) for row in cursor.fetchall()]
        if index % 25 == 0:
            print(f'Independent raw-source answers: {index+1}/200', flush=True)
    db.close()
    report = {'version': 'retail_ii_200_v1', 'frozen_at_utc': datetime.now(timezone.utc).isoformat(),
              'source_sha256': json.loads((DATA / 'source_manifest.json').read_text())['xlsx_sha256'],
              'oracle': 'DuckDB SQL over normalized original raw_lines, not production compiler or fact metrics',
              'limitation': '200 templated Chinese question instances; 50 development and 150 held-out instances share template families. Agent-authored, not independent human blind evaluation; not general enterprise/HR accuracy.',
              'numeric_tolerance': {'AOV_absolute': '0.0001', 'other_absolute': '0.000001'}, 'cases': output}
    BENCH.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    BENCH.with_suffix('.sha256').write_text(digest(BENCH) + '\n', encoding='ascii')
    print('Frozen 200 questions and raw-source SQL answers before model execution.', flush=True)


def canonical(row):
    equivalents = {'fact_retail_line__country': 'dim_country__country',
                   'fact_retail_line__stock_code': 'dim_product__stock_code'}
    return {equivalents.get(k, k): value for k, value in row.items()}


def matching_rows(actual, expected):
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    def matches(actual_row, ref):
        row = canonical(actual_row)
        if row.keys() != ref.keys():
            return False
        for key, value in ref.items():
            if value is None:
                if row[key] is not None:
                    return False
            elif key in FORMULAS:
                try:
                    first, second = Decimal(str(row[key])), Decimal(str(value))
                    tolerance = Decimal('0.0001') if key == 'AOV' else Decimal('0.000001')
                    if not first.is_finite() or not second.is_finite() or abs(first-second) > tolerance:
                        return False
                except (InvalidOperation, ValueError, TypeError):
                    return False
            elif row[key] != value:
                return False
        return True
    remaining = list(actual)
    for ref in expected:
        index = next((i for i, row in enumerate(remaining) if matches(row, ref)), None)
        if index is None:
            return False
        remaining.pop(index)
    return True


def passed_case(terminal, case):
    if terminal.get('type') != case.get('terminal', 'result'):
        return False
    if 'expected' in case and not matching_rows(terminal.get('data'), case['expected']):
        return False
    if 'comparison' in case:
        if not matching_rows(terminal.get('comparison_data'), case['comparison']):
            return False
        # Verify downstream arithmetic, not just the two input periods.
        analysis = terminal.get('analysis') or []
        if len(analysis) != 1:
            return False
        for metric in case['metrics']:
            current, baseline = Decimal(str(case['expected'][0][metric])), Decimal(str(case['comparison'][0][metric]))
            expected_delta = current-baseline
            actual = analysis[0].get('metrics', {}).get(metric, {})
            try:
                if abs(Decimal(str(actual.get('difference')))-expected_delta) > Decimal('0.0002'):
                    return False
                if baseline and abs(Decimal(str(actual.get('change_percent')))-expected_delta/abs(baseline)*100) > Decimal('0.0002'):
                    return False
            except (InvalidOperation, TypeError):
                return False
    return True


def run(args, *, benchmark_path=BENCH, checker=passed_case, report_prefix='retail_live'):
    sys.path.insert(0, str(ROOT / 'backend'))
    from improved.settings import load_env_file
    import os
    load_env_file()
    if digest(benchmark_path) != benchmark_path.with_suffix('.sha256').read_text().strip():
        raise RuntimeError('FROZEN_BENCHMARK_CHANGED')
    benchmark = json.loads(benchmark_path.read_text(encoding='utf-8'))
    selected = [c for c in benchmark['cases'] if args.split == 'all' or c['split'] == args.split][args.offset:]
    if args.limit:
        selected = selected[:args.limit]
    if args.ids:
        selected = [c for c in selected if c['id'] in args.ids]
    if not selected:
        raise RuntimeError('NO_EVALUATION_CASES_SELECTED')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    destination = ROOT / 'reports' / f'{report_prefix}_{args.split}_{stamp}.json'
    from app.conf.app_config import app_config
    def application_hash():
        hasher = hashlib.sha256()
        paths = []
        for directory in ('app', 'improved', 'prompts', 'conf'):
            paths.extend(p for p in (ROOT / 'backend' / directory).rglob('*') if p.is_file() and p.suffix in {'.py', '.txt', '.prompt', '.yaml'})
        for path in sorted(paths):
            hasher.update(path.relative_to(ROOT).as_posix().encode())
            hasher.update(path.read_bytes())
        return hasher.hexdigest()
    import inspect
    report = {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'benchmark_sha256': digest(benchmark_path),
              'checker_sha256':digest(Path(inspect.getsourcefile(checker))),
              'application_sha256': application_hash(), 'evaluator_sha256': digest(Path(__file__)),
              'provider': app_config.llm.provider, 'model': app_config.llm.model_name,
              'workers': args.workers, 'split': args.split, 'rule_fallback': False,
              'limitation': benchmark['limitation'], 'cases': []}
    headers = {'Authorization': 'Bearer ' + os.environ['DATA_AGENT_API_TOKEN']}
    with httpx.Client(base_url=f'http://127.0.0.1:{args.port}', timeout=75, trust_env=False, follow_redirects=False) as client:
        health = client.get('/api/health').json()
        if not health.get('ready') or health.get('dataset', {}).get('id') != 'retail_ii' or health.get('rule_fallback') is not False:
            raise RuntimeError('NOT_READY_RETAIL_APPLICATION')
        dispatch_lock = threading.Lock()
        next_start = [0.0]
        def query_one(case):
            with dispatch_lock:
                time.sleep(max(0, next_start[0]-time.perf_counter()))
                next_start[0] = time.perf_counter()+2.1
            start = time.perf_counter()
            events, request_id, status = [], None, None
            try:
                with client.stream('POST', '/api/query', headers=headers, json={'query': case['question']}) as response:
                    status = response.status_code
                    request_id = response.headers.get('x-request-id')
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line.startswith('data:'):
                            events.append(json.loads(line[5:]))
                terminal = next((e for e in reversed(events) if e.get('type') in {'result', 'clarification', 'error'}), {})
            except (httpx.HTTPError, ValueError) as error:
                terminal = {'type': 'transport_error', 'error_class': type(error).__name__}
            return {'id': case['id'], 'family': case['family'], 'split': case['split'], 'question': case['question'],
                      'passed': checker(terminal, case), 'elapsed_seconds': round(time.perf_counter()-start, 3),
                      'http_status': status, 'request_id': request_id, 'terminal': terminal,
                      'event_types': [e.get('type') for e in events]}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = [pool.submit(query_one, case) for case in selected]
            for number, future in enumerate(as_completed(pending), 1):
                record = future.result()
                report['cases'].append(record)
                report['passed'] = sum(c['passed'] for c in report['cases'])
                report['completed'] = len(report['cases'])
                destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                print(json.dumps({'n': number, 'of': len(selected), 'id': record['id'], 'passed': record['passed'],
                                  'terminal': record['terminal'].get('type'), 'seconds': record['elapsed_seconds']}, ensure_ascii=True), flush=True)
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    report['application_unchanged_during_run'] = report['application_sha256'] == application_hash()
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Saved {destination.name}: {report["passed"]}/{len(selected)} passed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'run'])
    parser.add_argument('--confirm-paid-llm-evaluation', action='store_true')
    parser.add_argument('--split', choices=['development', 'test', 'all'], default='development')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--workers', type=int, choices=[1, 2], default=1)
    parser.add_argument('--ids', nargs='+')
    args = parser.parse_args()
    if args.action == 'run' and not args.confirm_paid_llm_evaluation:
        parser.error('Live requests consume configured model API credits; pass --confirm-paid-llm-evaluation')
    if args.action == 'freeze':
        freeze()
    else:
        run(args)
