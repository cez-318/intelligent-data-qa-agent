"""Opt-in paid LLM verification, restricted to this machine's fictional fixture."""
import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import sys
import time
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from improved.settings import load_env_file
from check_local_stack import check
from app.conf.app_config import app_config

CASES = [
    {"question": "统计2026年成交总额", "expected": [{"GMV": 600}]},
    {"question": "统计2026年平均订单金额", "expected": [{"AOV": 200}]},
    {"question": "2026年广东的成交总额是多少？", "expected": [{"GMV": 400}]},
    {"question": "按省份统计2026年的成交总额", "expected": [{"GMV": 400, "dim_region__province": "广东"}, {"GMV": 200, "dim_region__province": "北京"}]},
    {"question": "对比2026年和2025年成交总额，计算同比变化", "expected": [{"GMV": 600}], "comparison": [{"GMV": 200}], "change_percent": 200},
    {"question": "统计1900年的成交总额", "expected": []},
    {"question": "统计2026年净利润", "terminal": "clarification"},
]


def matching_rows(actual, expected):
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    def matches(row, ref):
        if row.keys() != ref.keys():
            return False
        for key, value in ref.items():
            if isinstance(value, (int, float)):
                try:
                    if Decimal(str(row[key])) != Decimal(str(value)):
                        return False
                except (InvalidOperation, ValueError):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-paid-synthetic-test", action="store_true", required=True)
    args = parser.parse_args()
    load_env_file()
    # No production database or arbitrary URL is accepted by this test harness.
    stack = asyncio.run(check())
    assert app_config.llm.provider == "deepseek" and app_config.llm.base_url.rstrip("/") == "https://api.deepseek.com"
    headers = {"Authorization": "Bearer " + os.environ["DATA_AGENT_API_TOKEN"]}
    records = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=75, trust_env=False, follow_redirects=False) as client:
        health = client.get("/api/health").json()
        assert health["ready"] and health["mode"] == "llm_rag" and not health["rule_fallback"]
        unauthorized = client.post("/api/query", json={"query": "统计2026年成交总额"})
        assert unauthorized.status_code == 401
        for case in CASES:
            started = time.perf_counter()
            events = []
            with client.stream("POST", "/api/query", json={"query": case["question"]}, headers=headers) as response:
                response.raise_for_status()
                request_id = response.headers.get("x-request-id")
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        events.append(json.loads(line[5:]))
            terminal = next((event for event in reversed(events) if event.get("type") in {"result", "error", "clarification"}), {})
            passed = terminal.get("type") == case.get("terminal", "result")
            if "expected" in case:
                passed = passed and matching_rows(terminal.get("data"), case["expected"])
            if "comparison" in case:
                passed = passed and matching_rows(terminal.get("comparison_data"), case["comparison"])
                changes = terminal.get("analysis") or []
                passed = passed and len(changes) == 1 and changes[0].get("metrics", {}).get("GMV", {}).get("change_percent") == case["change_percent"]
            records.append({**case, "passed": bool(passed), "request_id": request_id,
                            "elapsed_seconds": round(time.perf_counter() - started, 3),
                            "events": [event.get("type") for event in events], "result": terminal})
            print(json.dumps({"question": case["question"], "passed": bool(passed), "terminal": terminal.get("type"), "seconds": records[-1]["elapsed_seconds"]}, ensure_ascii=False), flush=True)
    report = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "provider": app_config.llm.provider,
              "model": app_config.llm.model_name, "controlled_model": False, "fixture": stack["fixture"],
              "unauthorized_rejected": True, "stack": stack, "cases": records,
              "limitation": "Seven fictional-fixture smoke cases, not a representative accuracy benchmark or production acceptance."}
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = ROOT / "reports" / f"live_examples_{stamp}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {destination.name}; passed {sum(item['passed'] for item in records)}/{len(records)}")
    return 0 if all(item["passed"] for item in records) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        raise SystemExit(f"Live example verification failed ({type(error).__name__}); credentials were not displayed.") from None
