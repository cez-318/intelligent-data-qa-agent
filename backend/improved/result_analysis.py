"""Deterministic comparisons over returned values, never guessed causal claims."""
from decimal import Decimal


def compare_rows(rows, baseline, dimensions, metrics, *, rate_metrics=()):
    keys = [name.replace(".", "__") for name in dimensions]
    def index(data):
        return {tuple(row.get(key) for key in keys): row for row in data}
    current, previous = index(rows), index(baseline)
    result = []
    for group in current.keys() | previous.keys():
        item = {key: value for key, value in zip(keys, group)}
        changes = {}
        for name in metrics:
            now, old = current.get(group, {}).get(name), previous.get(group, {}).get(name)
            numeric = isinstance(now, (int, float, Decimal)) and isinstance(old, (int, float, Decimal))
            changes[name] = {"current": now, "previous": old,
                             "difference": round(float(now - old), 6) if numeric else None,
                             "change_percent": round(float((now - old) / old * 100), 4) if numeric and old != 0 and name not in rate_metrics else None,
                             "note": "比率指标请按配置单位理解差值，不计算相对增长率" if name in rate_metrics else ("缺期或基期为零时不计算增长率" if not numeric or old == 0 else "")}
        result.append({**item, "metrics": changes})
    return sorted(result, key=lambda item: str(item))
