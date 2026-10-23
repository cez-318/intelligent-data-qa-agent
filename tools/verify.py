"""Validate the real application graph with controlled external-service adapters.

This is a software regression test, not an LLM accuracy benchmark.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))


async def examples(directory):
    from app.services.query_service import QueryService
    from tests.support.ecommerce import Warehouse, Metadata, Retriever, Embedding, ScriptedModel
    cases = [
        ("2026年成交总额", {"metrics": ["GMV"], "filters": [{"field": "dim_date.year", "op": "eq", "value": 2026}]}, [{"GMV": 600}]),
        ("2026年平均订单金额", {"metrics": ["AOV"], "filters": [{"field": "dim_date.year", "op": "eq", "value": 2026}]}, [{"AOV": 200}]),
        ("2026年广东成交总额", {"metrics": ["GMV"], "filters": [{"field": "dim_date.year", "op": "eq", "value": 2026}, {"field": "dim_region.province", "op": "eq", "value": "广东"}]}, [{"GMV": 400}]),
        ("1900年成交总额", {"metrics": ["GMV"], "filters": [{"field": "dim_date.year", "op": "eq", "value": 1900}]}, []),
    ]
    records = []
    for index, (question, plan, expected) in enumerate(cases):
        database, metadata = Warehouse(directory / f"case{index}.sqlite3"), Metadata()
        service = QueryService(Embedding(), Retriever(list(metadata.columns.values())), Retriever([]), Retriever(metadata.metrics), metadata, database)
        model = ScriptedModel({"mode": "metric", "plan": plan})
        with patch("app.agent.llm.get_model", return_value=model):
            events = [json.loads(chunk.removeprefix("data: ").strip()) async for chunk in service.query(question)]
        result = next((e for e in events if e["type"] == "result"), {})
        records.append({"question": question, "expected": expected, "passed": result.get("data") == expected,
                        "controlled_model": True, "model_stages": model.calls, "result": result})
    return records


def main():
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    cmd = [sys.executable, "-m", "pytest", "--tb=short", "--cov=improved", "--cov=app.agent",
           "--cov=app.repositories.mysql.dw", "--cov=app.services.query_service", "--cov=main",
           "--cov-report=term-missing", f"--cov-report=json:{reports / 'coverage.json'}",
           f"--junitxml={reports / 'junit.xml'}"]
    run = subprocess.run(cmd, cwd=BACKEND, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                         capture_output=True, text=True, encoding="utf-8")
    (reports / "pytest.txt").write_text(run.stdout + run.stderr, encoding="utf-8")
    print(run.stdout)
    with TemporaryDirectory(prefix="qa-graph-") as directory:
        records = asyncio.run(examples(Path(directory)))
    (reports / "main_flow_examples.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    suite = ET.parse(reports / "junit.xml").getroot().find("testsuite")
    coverage = json.loads((reports / "coverage.json").read_text(encoding="utf-8"))["totals"]["percent_covered"]
    manifest = json.loads((ROOT / "source_manifest.json").read_text(encoding="utf-8"))
    original_paths = [ROOT.parent / "3.代码" / name for name in manifest]
    original_available = all(path.is_file() for path in original_paths)
    unchanged = (all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                     for path, digest in zip(original_paths, manifest.values()))
                 if original_available else None)
    source_check = ("True" if unchanged is True else
                    "False" if unchanged is False else
                    "未随发布包提供，已跳过；不影响源码回归")
    lines = ["# 原项目主流程优化：验证报告", "", f"生成时间（UTC）：{datetime.now(timezone.utc).isoformat()}", "",
             f"- 回归测试：{suite.attrib['tests']} 项，失败 {suite.attrib['failures']}，错误 {suite.attrib['errors']}。",
             f"- 主流程/安全模块语句覆盖率：{coverage:.2f}%（不是整个仓库覆盖率）。",
             f"- 原始压缩包 SHA-256 未变化：{source_check}。", "",
             "## 此次测试到底验证了什么", "",
             "运行生产入口使用的 QueryService 和完整 LangGraph，包含三路召回、合并筛选、LLM调用消息封装、结构化计划、SQL编译校验、实际SQLite执行和SSE输出。",
             "外部LLM、Embedding、ES、Qdrant及元数据库在测试中使用受控适配器；不是生产运行时的降级方式。MySQL驱动测试使用模拟会话。",
             "测试包含修复后复检、指标/明细/分组对比、无数据、澄清、非法SQL和未配置服务不降级。历史规则用例仅保留为回归测试，不计入问数准确率。", "",
             "## 实例数据核对", "", "原项目电商星型结构，5条虚构订单：2026年金额100、300、200；2025年100、100。", "",
             "| 问题 | 预期 | 实际 | 核对 |", "|---|---|---|---|"]
    for item in records:
        lines.append(f"| {item['question']} | {json.dumps(item['expected'], ensure_ascii=False)} | {json.dumps(item['result'].get('data'), ensure_ascii=False)} | {item['passed']} |")
    lines += ["", "## 未完成的真实环境验收", "",
              "本报告本身是离线回归；当前真实DeepSeek、MySQL及三路检索的全量记录见《真实零售数据评测报告.md》和retail_live_*_20260929*.json。虚构样例结果不代表线上准确率、响应时间或提升幅度。",
              "健康检查不包含付费LLM生成探测；ready只表示已配置且启动依赖检查通过，模型认证/输出质量需实际查询验证。",
              "还需确认业务口径、真实数据权限、并发及超时行为；不能直接宣称生产验收通过。",
              "发布包已移除旧规则演示报告；当前结论以稳定性、真实零售、贡献分解和随机实验四类报告为准。"]
    (reports / "主流程验证报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if run.returncode == 0 and unchanged is not False and all(x["passed"] for x in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
