"""Restore authorized keys and bridge tables from trusted server metadata."""
from collections import deque
from copy import deepcopy
from pathlib import Path
import yaml
from improved.guard import QueryRejected
from improved.profiles import active_profile

CONF = Path(__file__).resolve().parents[1] / "conf"


def enrich_context(table_infos, metric_infos):
    CONF = active_profile().conf
    metadata = yaml.safe_load((CONF / "meta_config.yaml").read_text(encoding="utf-8"))
    rules = yaml.safe_load((CONF / "rag_semantics.yaml").read_text(encoding="utf-8"))
    policy = yaml.safe_load((CONF / "query_policy.yaml").read_text(encoding="utf-8"))["tables"]
    trusted = {t["name"]: t for t in metadata["tables"]}
    retrieved = {(t["name"], c["name"]): c for t in table_infos for c in t["columns"]}
    selected = {t["name"]: {c["name"] for c in t["columns"] if c["name"] in policy.get(t["name"], [])}
                for t in table_infos if t["name"] in policy}
    metrics = deepcopy(metric_infos)
    for metric in metrics:
        rule = rules["metrics"].get(metric["name"])
        if rule:
            metric.update(rule)
            metric["semantic_version"] = rules["version"]
            for field in rule["required_columns"]:
                table, column = field.split(".")
                if column not in policy.get(table, []):
                    raise QueryRejected("METRIC_NOT_AUTHORIZED")
                selected.setdefault(table, set()).add(column)
    if not selected:
        raise QueryRejected("NO_AUTHORIZED_TABLE")
    adjacency = {table: [] for table in policy}
    for left, lcol, right, rcol in rules["relationships"]:
        if lcol in policy.get(left, []) and rcol in policy.get(right, []):
            adjacency[left].append(right)
            adjacency[right].append(left)
    root = next(iter(selected))
    for target in list(selected):
        queue = deque([(root, [root])])
        visited = set()
        path = None
        while queue:
            node, chain = queue.popleft()
            if node == target:
                path = chain
                break
            if node in visited:
                continue
            visited.add(node)
            queue.extend((neighbor, chain + [neighbor]) for neighbor in adjacency[node] if neighbor not in visited)
        if path is None:
            raise QueryRejected("NO_APPROVED_JOIN_PATH")
        for table in path:
            selected.setdefault(table, set())
    result = []
    for name, columns in selected.items():
        table = deepcopy(trusted[name])
        for column in table["columns"]:
            if column["role"] in {"primary_key", "foreign_key"}:
                columns.add(column["name"])
        table["columns"] = [c for c in table["columns"] if c["name"] in columns and c["name"] in policy[name]]
        for column in table["columns"]:
            source = retrieved.get((name, column["name"]), {})
            # Preserve retrieval evidence without letting it replace trusted roles/joins.
            for key in ("examples", "type"):
                if key in source:
                    column[key] = deepcopy(source[key])
        table["approved_relationships"] = [r for r in rules["relationships"] if name in (r[0], r[2]) and r[0] in selected and r[2] in selected]
        result.append(table)
    return result, metrics
