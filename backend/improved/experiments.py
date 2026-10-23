"""Registered individual-randomized binary-outcome analyses, not causal discovery."""
import math
from statistics import NormalDist
from scipy.stats import chisquare


class ExperimentRejected(ValueError):
    pass


def _count(value, n=None):
    if type(value) is not int or value < 0 or (n is not None and value > n):
        raise ExperimentRejected('INVALID_COUNTS')
    return value


def newcombe_interval(x, n, y, m, alpha):
    _count(n)
    _count(m)
    _count(x,n)
    _count(y,m)
    if not n or not m or not 0 < alpha < 1:
        raise ExperimentRejected('INVALID_INTERVAL_INPUT')
    z = NormalDist().inv_cdf(1-alpha/2)
    def wilson(k, count):
        p = k/count
        center = (p+z*z/(2*count))/(1+z*z/count)
        radius = z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/(1+z*z/count)
        return max(0,center-radius), min(1,center+radius)
    p1,p0 = x/n,y/m
    low1,high1 = wilson(x,n)
    low0,high0 = wilson(y,m)
    diff = p1-p0
    return (diff-math.hypot(p1-low1,high0-p0), diff+math.hypot(high1-p1,p0-low0))


def analyze_binary_experiment(groups, design):
    allocation = design.get('allocation',{})
    outcomes = design.get('outcomes',{})
    control = design.get('control')
    alpha = design.get('family_alpha',.05)
    if (design.get('design') != 'individual_randomized' or not design.get('randomization_source')
            or control not in allocation or len(allocation)<2 or set(groups)!=set(allocation)
            or not outcomes or not 0 < alpha < 1
            or any(type(p) not in (int,float) or not math.isfinite(p) or p<=0 for p in allocation.values())
            or not math.isclose(sum(allocation.values()),1,abs_tol=1e-12)):
        raise ExperimentRejected('UNSUPPORTED_OR_UNDOCUMENTED_DESIGN')
    for values in groups.values():
        n=_count(values.get('n'))
        if n < max(20,design.get('minimum_arm_size',20)):
            raise ExperimentRejected('INSUFFICIENT_SAMPLE')
        for outcome in outcomes:
            _count(values.get(outcome),n)
    total=sum(g['n'] for g in groups.values())
    srm=chisquare([groups[a]['n'] for a in allocation], [total*p for p in allocation.values()])
    diagnostics={'sample_ratio_chi2':float(srm.statistic), 'sample_ratio_p':float(srm.pvalue),
                 'sample_ratio_threshold':design.get('srm_alpha',.001), 'total_n':total,
                 'arms':groups}
    if srm.pvalue < diagnostics['sample_ratio_threshold']:
        return {'status':'unavailable','reason':'sample_ratio_mismatch','diagnostics':diagnostics}
    comparisons=(len(groups)-1)*len(outcomes)
    effects=[]
    for arm,values in groups.items():
        if arm==control:
            continue
        for outcome,label in outcomes.items():
            x,n=values[outcome],values['n']
            y,m=groups[control][outcome],groups[control]['n']
            diff=x/n-y/m
            low,high=newcombe_interval(x,n,y,m,alpha/comparisons)
            effects.append({'treatment':arm,'control':control,'outcome':outcome,'outcome_label':label,
                            'treatment_n':n,'control_n':m,'treatment_events':x,'control_events':y,
                            'treatment_rate':x/n,'control_rate':y/m,'risk_difference':diff,
                            'effect_percentage_points':diff*100,'ci_low':low,'ci_high':high,
                            'ci_low_percentage_points':low*100,'ci_high_percentage_points':high*100,
                            'relative_lift_percent':diff/(y/m)*100 if y else None,
                            'incremental_events_per_1000':diff*1000,
                            'direction':'positive' if low>0 else ('negative' if high<0 else 'inconclusive')})
    return {'status':'complete','method':'ITT risk difference; Wilson/Newcombe; Bonferroni',
            'causal_scope':'conditional_on_documented_random_assignment_and_valid_followup',
            'family_confidence':1-alpha,'interval_level':1-alpha/comparisons,
            'comparison_count':comparisons,'effects':effects,'diagnostics':diagnostics,
            'interpretation':'按原始随机分配估计两周平均意向处理效应；区间包含0表示证据不足，不代表证明无效。',
            'limitations':['随机化依据来自研究发布者说明，并未审计原始分配日志。',
                           '因果解读仍依赖分配有效、结果完整、无组间干扰及一致性；样本比例检验通过不能证明这些假设。',
                           '区间为固定终点近似区间，经预先固定的全部比较数校正；不适用于反复窥视、自动挑选子组或连续监控。',
                           '估计仅适用于本实验人群、干预和观察窗口，不能外推成人力政策效果。']}
