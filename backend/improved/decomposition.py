"""Exact accounting decompositions; no causal claims or inferred policy effects."""
from decimal import Decimal, InvalidOperation, localcontext


class AnalysisRejected(ValueError):
    pass


def number(value):
    if value is None or isinstance(value, bool):
        raise AnalysisRejected('MISSING_OR_INVALID_MEASURE')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise AnalysisRejected('INVALID_MEASURE') from None
    if not result.is_finite():
        raise AnalysisRejected('NONFINITE_MEASURE')
    return result


def segment_contributions(rows, baseline, dimension, metric, current_total, previous_total, *, display_limit=10):
    if not 1 <= display_limit <= 50:
        raise AnalysisRejected('INVALID_DISPLAY_LIMIT')
    def index(items):
        values = {}
        for row in items:
            if dimension not in row or row[dimension] in values:
                raise AnalysisRejected('MISSING_OR_DUPLICATE_GROUP_KEY')
            values[row[dimension]] = number(row.get(metric))
        return values
    now, old = index(rows), index(baseline)
    current, previous = number(current_total), number(previous_total)
    if sum(now.values(), Decimal(0)) != current or sum(old.values(), Decimal(0)) != previous:
        raise AnalysisRejected('INCOMPLETE_OR_NONADDITIVE_GROUPS')
    delta = current-previous
    with localcontext() as context:
        context.prec = 50
        complete = []
        for group in now.keys() | old.keys():
            change = now.get(group, Decimal(0))-old.get(group, Decimal(0))
            complete.append({'group': group, 'current': now.get(group, Decimal(0)),
                             'previous': old.get(group, Decimal(0)), 'difference': change,
                             'presence': 'both' if group in now and group in old else ('current_only' if group in now else 'previous_only'),
                             'contribution_percent': change/delta*100 if delta else None})
        complete.sort(key=lambda row: (-abs(row['difference']), str(row['group'])))
        displayed, remaining = complete[:display_limit], complete[display_limit:]
        remainder = {key: sum((r[key] for r in remaining), Decimal(0)) for key in ('current','previous','difference')}
        remainder['group_count'] = len(remaining)
        remainder['contribution_percent'] = remainder['difference']/delta*100 if delta else None
        residual = delta-sum((r['difference'] for r in complete), Decimal(0))
        return {'kind': 'segments', 'metric': metric, 'dimension': dimension,
                'current': current, 'previous': previous, 'difference': delta,
                'group_count': len(complete), 'rows': displayed, 'remainder': remainder,
                'gross_movement': sum((abs(r['difference']) for r in complete), Decimal(0)),
                'reconciliation_residual': residual, 'causal': False,
                'missing_group_policy': 'closed_snapshot_zero_only_after_complete_group_and_total_reconciliation',
                'note': '会计贡献分解，不是因果效应。覆盖已加载历史快照；单侧缺组在完整分组与总额核对后按0计，不代表真实世界无业务。贡献率=分组变化/总变化，可为负或超过100%；总变化为0时不计算。按绝对变化排序，未展示分组归入其余。'}


def volume_value_decomposition(current_revenue, current_orders, previous_revenue, previous_orders):
    now, n1, old, n0 = map(number, (current_revenue,current_orders,previous_revenue,previous_orders))
    if n1 <= 0 or n0 <= 0 or n1 != n1.to_integral_value() or n0 != n0.to_integral_value():
        raise AnalysisRejected('POSITIVE_INTEGER_ORDER_COUNTS_REQUIRED')
    with localcontext() as context:
        context.prec = 50
        a1, a0 = now/n1, old/n0
        volume = (n1-n0)*(a1+a0)/2
        value = (a1-a0)*(n1+n0)/2
        delta = now-old
        residual = delta-volume-value
        if abs(residual) > Decimal('0.000001'):
            raise AnalysisRejected('FACTOR_RECONCILIATION_FAILED')
        return {'kind': 'volume_value', 'current': now, 'previous': old, 'difference': delta,
                'current_orders': n1, 'previous_orders': n0, 'current_aov': a1, 'previous_aov': a0,
                'order_count_effect': volume, 'average_order_value_effect': value,
                'order_count_contribution_percent': volume/delta*100 if delta else None,
                'aov_contribution_percent': value/delta*100 if delta else None,
                'reconciliation_residual': residual, 'causal': False,
                'formula': '数量贡献=(N1-N0)*(A1+A0)/2；均额贡献=(A1-A0)*(N1+N0)/2；A=销售额/去重订单数',
                'note': '两种替换顺序取平均，使用未四舍五入的总额/订单数，两个贡献相加还原销售额变化。客单价包含组合变化，不等于商品定价效应，更不是政策因果效应。'}
