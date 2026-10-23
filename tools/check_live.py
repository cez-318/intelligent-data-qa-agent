"""Opt-in real-service smoke check; never logs query results or credentials."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from improved.settings import load_env_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--question", help="Runs real LLM inference against the configured data source; may incur fees")
    args = parser.parse_args()
    url = urlsplit(args.url)
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}):
        parser.error("Use HTTPS for a remote service")
    load_env_file()
    with httpx.Client(timeout=70, follow_redirects=False) as client:
        response = client.get(args.url.rstrip("/") + "/api/health")
        response.raise_for_status()
        health = response.json()
        print(json.dumps(health, ensure_ascii=False))
        if not health.get("ready") or health.get("mode") != "llm_rag":
            return 2
        if not args.question:
            print("Dependencies ready; no LLM inference was requested or verified.")
            return 0
        token = os.environ.get("DATA_AGENT_API_TOKEN")
        if not token:
            print("DATA_AGENT_API_TOKEN is not configured")
            return 2
        started, terminal, stages = time.perf_counter(), None, []
        with client.stream("POST", args.url.rstrip("/") + "/api/query",
                           headers={"Authorization": f"Bearer {token}"}, json={"query": args.question}) as response:
            response.raise_for_status()
            request_id = response.headers.get("x-request-id")
            for line in response.iter_lines():
                if line.startswith("data:"):
                    event = json.loads(line[5:])
                    stages.append(event.get("type"))
                    if event.get("type") in {"result", "error", "clarification"}:
                        terminal = event["type"]
        print(json.dumps({"request_id": request_id, "events": stages, "terminal": terminal,
                          "elapsed_seconds": round(time.perf_counter()-started, 3),
                          "answer_correctness": "not_evaluated"}))
        return 0 if terminal == "result" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (httpx.HTTPError, ValueError):
        print("Live check failed: verify service address, configuration and credentials.")
        raise SystemExit(2)
