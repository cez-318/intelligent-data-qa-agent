import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from retail_benchmark import cases, oracle_sql, matching_rows, passed_case


def test_frozen_design_and_separate_oracle():
    items = cases()
    assert len(items) == len({x['question'] for x in items}) == 200
    assert sum(x['split'] == 'development' for x in items) == 50
    assert sum(x['split'] == 'test' for x in items) == 150
    for item in items:
        if not item.get('terminal'):
            sql, params = oracle_sql(item)
            assert 'FROM raw_lines' in sql
            assert 'fact_retail_line' not in sql
            assert sql.count('?') == len(params)


def test_numeric_tolerance_null_and_duplicate_rows():
    assert matching_rows([{'AOV': '1.33333333'}], [{'AOV': 1.33333333333}])
    assert not matching_rows([{'AOV': 1.33}], [{'AOV': 1.33333333333}])
    assert not matching_rows([{'SALES_AMOUNT': None}], [{'SALES_AMOUNT': 0}])
    assert not matching_rows([{'ORDER_COUNT': 2}], [{'ORDER_COUNT': 2}, {'ORDER_COUNT': 2}])
    assert matching_rows([{'fact_retail_line__country': 'France', 'ORDER_COUNT': '2'}], [{'dim_country__country': 'France', 'ORDER_COUNT': 2}])


def test_comparison_checks_arithmetic_and_baseline():
    case = {'metrics': ['SALES_AMOUNT'], 'expected': [{'SALES_AMOUNT': '120'}], 'comparison': [{'SALES_AMOUNT': '100'}]}
    result = {'type': 'result', 'data': [{'SALES_AMOUNT': 120}], 'comparison_data': [{'SALES_AMOUNT': 100}],
              'analysis': [{'metrics': {'SALES_AMOUNT': {'difference': 20, 'change_percent': 20}}}]}
    assert passed_case(result, case)
    result['analysis'][0]['metrics']['SALES_AMOUNT']['difference'] = 30
    assert not passed_case(result, case)
