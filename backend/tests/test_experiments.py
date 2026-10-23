import math
import pytest
from improved.experiments import analyze_binary_experiment, ExperimentRejected, newcombe_interval


def design():
    return {'design':'individual_randomized', 'randomization_source':'https://example.org/study',
            'control':'control','allocation':{'control':1/3,'a':1/3,'b':1/3},
            'outcomes':{'conversion':'购买率','visit':'访问率'}, 'family_alpha':0.05,
            'srm_alpha':0.001, 'minimum_arm_size':20}


def groups():
    return {'control':{'n':1000,'conversion':100,'visit':200},
            'a':{'n':1000,'conversion':200,'visit':300},
            'b':{'n':1000,'conversion':100,'visit':200}}


def test_family_adjustment_and_effect_not_relative_percent():
    result = analyze_binary_experiment(groups(),design())
    assert result['status'] == 'complete'
    assert result['comparison_count'] == 4
    assert result['interval_level'] == 0.9875
    row = result['effects'][0]
    assert row['risk_difference'] == pytest.approx(.1)
    assert row['effect_percentage_points'] == pytest.approx(10)
    assert row['direction'] == 'positive'
    assert result['effects'][2]['direction'] == 'inconclusive'


@pytest.mark.parametrize('x,n,y,m', [(0,100,0,100),(100,100,0,100),(20,100,10,150),(1,50,3,45)])
def test_newcombe_matches_independent_statsmodels(x,n,y,m):
    from statsmodels.stats.proportion import confint_proportions_2indep
    assert newcombe_interval(x,n,y,m,.0125) == pytest.approx(
        confint_proportions_2indep(x,n,y,m,method='newcomb',compare='diff',alpha=.0125),abs=1e-12)


def test_all_zero_has_interval_and_does_not_prove_no_effect():
    data=groups()
    for row in data.values():
        row['conversion']=0
    result=analyze_binary_experiment(data,design())
    row=result['effects'][0]
    assert row['ci_low'] < 0 < row['ci_high']
    assert row['relative_lift_percent'] is None
    assert row['direction']=='inconclusive'


def test_sample_ratio_mismatch_blocks_effect_claim():
    data=groups()
    data['a']['n']=10000
    result=analyze_binary_experiment(data,design())
    assert result['status']=='unavailable'
    assert result['reason']=='sample_ratio_mismatch'
    assert 'effects' not in result


@pytest.mark.parametrize('change', [
    {'design':'observational'}, {'randomization_source':''},
    {'allocation':{'control':.5,'a':.5}}, {'family_alpha':0},
    {'control':'missing'}, {'outcomes':{}},
])
def test_unapproved_design_fails_closed(change):
    with pytest.raises(ExperimentRejected):
        analyze_binary_experiment(groups(),{**design(),**change})


@pytest.mark.parametrize('field,value', [('n',0),('n',True),('conversion',None),('conversion',1001),('visit',-1),('visit',math.nan)])
def test_bad_aggregates_never_imputed(field,value):
    data=groups()
    data['a'][field]=value
    with pytest.raises(ExperimentRejected):
        analyze_binary_experiment(data,design())


def test_small_groups_and_missing_arms_fail_closed():
    data=groups()
    data['a']={'n':10,'conversion':1,'visit':2}
    with pytest.raises(ExperimentRejected):
        analyze_binary_experiment(data,design())


@pytest.mark.parametrize('args',[(0,0,0,10,.05),(0,10,0,10,0),(0,10,0,10,1)])
def test_invalid_interval_design_is_rejected(args):
    with pytest.raises(ExperimentRejected):
        newcombe_interval(*args)


def test_negative_effect_is_not_labeled_positive():
    data=groups()
    data['a']['conversion']=0
    assert analyze_binary_experiment(data,design())['effects'][0]['direction']=='negative'
    del data['a']
    with pytest.raises(ExperimentRejected):
        analyze_binary_experiment(data,design())
