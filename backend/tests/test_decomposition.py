from decimal import Decimal
import pytest
from improved.decomposition import segment_contributions, volume_value_decomposition, AnalysisRejected
from improved.decomposition import number


@pytest.mark.parametrize('value', [None, True, 'not-a-number', 'Infinity'])
def test_invalid_numeric_inputs(value):
    with pytest.raises(AnalysisRejected):
        number(value)


@pytest.mark.parametrize('limit', [0, 51])
def test_display_limit_is_bounded(limit):
    with pytest.raises(AnalysisRejected):
        segment_contributions([], [], 'g', 'M', 0, 0, display_limit=limit)


def test_full_population_with_entrants_exits_and_remainder():
    now = [{'country':'A','SALES_AMOUNT':150}, {'country':'B','SALES_AMOUNT':30}, {'country':'C','SALES_AMOUNT':20}]
    old = [{'country':'A','SALES_AMOUNT':100}, {'country':'B','SALES_AMOUNT':50}, {'country':'D','SALES_AMOUNT':10}]
    result = segment_contributions(now, old, 'country', 'SALES_AMOUNT', 200, 160, display_limit=2)
    assert result['difference'] == Decimal(40)
    assert result['reconciliation_residual'] == 0
    assert result['group_count'] == 4
    assert sum(r['difference'] for r in result['rows']) + result['remainder']['difference'] == 40
    assert result['rows'][0]['contribution_percent'] == 125
    assert result['missing_group_policy'].startswith('closed_snapshot')


def test_offsetting_changes_do_not_divide_by_zero():
    result = segment_contributions([{'g':'a','M':20},{'g':'b','M':10}], [{'g':'a','M':10},{'g':'b','M':20}], 'g','M',30,30)
    assert result['difference'] == 0
    assert all(r['contribution_percent'] is None for r in result['rows'])
    assert result['gross_movement'] == 20


@pytest.mark.parametrize('now,old,current,previous', [
    ([{'g':'a','M':2}], [{'g':'a','M':1}], 3, 1),
    ([{'g':'a','M':2},{'g':'a','M':2}], [{'g':'a','M':1}], 4, 1),
    ([{'g':'a','M':None}], [{'g':'a','M':1}], 0, 1),
    ([{'g':'a','M':'NaN'}], [{'g':'a','M':1}], 0, 1),
])
def test_invalid_or_incomplete_groups_fail_closed(now,old,current,previous):
    with pytest.raises(AnalysisRejected):
        segment_contributions(now,old,'g','M',current,previous)


def test_unknown_dimension_is_retained_as_a_bucket():
    result = segment_contributions([{'g':None,'M':20}], [{'g':None,'M':10}], 'g','M',20,10)
    assert result['rows'][0]['group'] is None
    assert result['difference'] == 10


def test_symmetric_order_count_and_average_order_value():
    result = volume_value_decomposition(300, 12, 200, 10)
    assert result['order_count_effect'] == 45
    assert result['average_order_value_effect'] == 55
    assert result['difference'] == 100
    assert result['reconciliation_residual'] == 0
    assert result['causal'] is False


@pytest.mark.parametrize('args', [(0,0,100,5), (100,5,0,0), (100,-1,200,2), (100,1.5,200,2)])
def test_zero_or_invalid_order_denominator_is_not_imputed(args):
    with pytest.raises(AnalysisRejected):
        volume_value_decomposition(*args)


def test_fractional_aov_uses_unrounded_totals():
    result = volume_value_decomposition(Decimal('11.000001'),3,Decimal('10'),7)
    assert abs(result['reconciliation_residual']) < Decimal('0.000001')
    assert abs(result['order_count_effect'] + result['average_order_value_effect'] - Decimal('1.000001')) < Decimal('0.000001')
