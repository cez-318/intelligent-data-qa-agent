"""Summarize every completed evaluation run without discarding failed cases."""
from collections import Counter
import json
from pathlib import Path
import statistics
from retail_pipeline import ROOT
from retail_benchmark import BENCH, FORMULAS


def percentile(values, p):
    values = sorted(values)
    position = (len(values)-1)*p
    lower = int(position)
    return values[lower] + (values[min(lower+1,len(values)-1)]-values[lower])*(position-lower)


def diagnose(record, case):
    terminal = record['terminal']
    if terminal.get('type') != case.get('terminal','result'):
        if case.get('family') == 'no_data' and terminal.get('type') == 'clarification':
            return '超出历史覆盖范围时返回澄清，未按接口约定返回空结果；不是数值计算错误'
        return '终态不符合预期：' + str(terminal.get('type'))
    plan = terminal.get('evidence',{}).get('query_plan') or {}
    if set(plan.get('metrics',[])) != set(case.get('metrics',[])):
        return '指标选择不同于要求'
    if case.get('top') and (plan.get('order_by') != case['metrics'][0] or not plan.get('descending')):
        return '排名排序字段或方向缺失/错误'
    if case.get('country') and not any(f.get('value') == case['country'] for f in plan.get('filters',[])):
        return '国家筛选遗漏或取值错误'
    return '结果/粒度/期间或比较计算不一致，需查看原始计划和标准SQL'


def main():
    reports = ROOT / 'reports'
    runs = []
    for path in sorted(reports.glob('retail_live_*.json')):
        report = json.loads(path.read_text(encoding='utf-8'))
        if report.get('finished_at_utc'):
            runs.append((path, report))
    tests = [(p,r) for p,r in runs if r['split']=='test' and r['completed']==150]
    if not tests:
        raise RuntimeError('NO_COMPLETED_150_CASE_TEST_REPORT')
    # Always expose all rounds; use the FIRST complete held-out run as headline.
    path, tested = tests[0]
    cases = {c['id']:c for c in json.loads(BENCH.read_text(encoding='utf-8'))['cases']}
    audit = json.loads((reports / 'retail_installation_audit.json').read_text(encoding='utf-8'))
    query_cases = [r for r in tested['cases'] if r['family'] != 'unsupported']
    unsupported = [r for r in tested['cases'] if r['family'] == 'unsupported']
    latencies = [r['elapsed_seconds'] for r in tested['cases']]
    sql_times = [r['terminal']['execution_ms'] for r in tested['cases'] if 'execution_ms' in r['terminal']]
    summary = {
        'headline_report': path.name, 'model': tested['model'], 'test_passed': tested['passed'], 'test_total': tested['completed'],
        'test_success_pct': round(tested['passed']/tested['completed']*100,2),
        'query_passed': sum(r['passed'] for r in query_cases), 'query_total': len(query_cases),
        'unsupported_handled': sum(r['passed'] for r in unsupported), 'unsupported_total': len(unsupported),
        'latency_seconds': {'median': round(statistics.median(latencies),3), 'p95': round(percentile(latencies,.95),3), 'max': max(latencies)},
        'sql_ms': {'median': round(statistics.median(sql_times),2), 'p95': round(percentile(sql_times,.95),2)},
        'workers': tested['workers'], 'application_unchanged': tested['application_unchanged_during_run'],
        'failed': [{'id':r['id'], 'question':r['question'], 'reason':diagnose(r,cases[r['id']])} for r in tested['cases'] if not r['passed']],
        'benchmark_sha256': tested['benchmark_sha256'], 'application_sha256': tested['application_sha256'],
    }
    (reports/'retail_evaluation_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['# 百万行真实零售数据：接入与留出集评测', '',
             '## 结论', '',
             f"原项目主流程已接入 {audit['raw_rows']:,} 条 UCI 真实历史零售明细、{audit['countries']} 个国家/地区、{audit['stock_codes']:,} 个商品代码和 8 个注册指标。不是另起一个规则 demo。",
             f"首次完整留出评测：**{tested['passed']}/{tested['completed']}（{summary['test_success_pct']}%）任务成功**。其中有标准结果的查询 {summary['query_passed']}/{summary['query_total']}，不支持问题的澄清终态 {summary['unsupported_handled']}/{summary['unsupported_total']}。",
             '这不是企业通用准确率：200条模板化中文实例由开发助手编写；50开发、150留出共享题型，不是人工独立盲测。金额、计数、客单价分别按公开记录和声明口径独立计算，公开数据本身没有官方中文问答标准答案。', '',
             '## 不隐藏开发与评测历史', '', '| 报告 | 集合 | 通过/完成 |', '|---|---|---|']
    for run_path, report in runs:
        lines.append(f"| {run_path.name} | {report['split']} | {report['passed']}/{report['completed']} |")
    lines += ['', '首轮开发集失败涉及数量/金额混淆、Top10漏排序、国家筛选遗漏。只更新了通用计划约束，随后仅复测原3道失败题；3/3不表示修订后完整50题达到100%。留出集合在模型运行前冻结，未用于修改上述约束，失败项也不从分母剔除。', '',
              '## 按题型分解', '', '| 题型 | 通过/总数 |', '|---|---|']
    for family in sorted({r['family'] for r in tested['cases']}):
        group = [r for r in tested['cases'] if r['family']==family]
        lines.append(f"| {family} | {sum(r['passed'] for r in group)}/{len(group)} |")
    lines += ['', '## 留出失败项', '']
    lines += [f"- {r['id']}：{r['question']} —— {r['reason']}。" for r in summary['failed']] or ['本次留出集没有发现失败项；仍不能外推为所有问题都正确。']
    lines += ['', '不针对本轮留出失败调参后重新把同一批题称为新留出验证。后续修复应补回归并另冻结新的时间/实体/题型留出集。', '',
              '## 性能（仅本机本次）', '',
              f"- 模型：{tested['model']}；最多 {tested['workers']} 路并发、间隔至少2.1秒发起。",
              f"- 端到端延迟中位数 {summary['latency_seconds']['median']} 秒，P95 {summary['latency_seconds']['p95']} 秒，最大 {summary['latency_seconds']['max']} 秒；包括失败、检索、模型与传输，不含调度排队等待。",
              f"- 返回结果的SQL阶段中位数 {summary['sql_ms']['median']} ms，P95 {summary['sql_ms']['p95']} ms；对比题包括两期执行。不是纯数据库基准。",
              '- CPU Embedding、本机 Docker、网络与同时进行的安装审计/回归测试会影响结果；不是线上SLA或高并发容量承诺。', '',
              '## 数据质量与隔离', '',
              f"- 缺失客户 {audit['missing_customers']:,} 行（{audit['missingness_pct']['missing_customers']}%）；保留合格销售金额，客户数只计已知编号。",
              f"- 完全相同记录额外 {audit['duplicate_extra_rows']:,} 行（{audit['missingness_pct']['duplicate_extra_rows']}%）；保留而不是猜测删除。",
              f"- 缺失描述 {audit['missing_descriptions']:,} 行，缺失日期 {audit['missing_dates']} 行。维度连接后仍为 {audit['join_row_count']:,} 行，孤儿维度数 {audit['orphan_counts']}。",
              f"- 同发票跨国家数 {audit['invoice_multi_country']}、跨已知客户数 {audit['invoice_multi_customer']}。",
              '- 全量导入无MySQL警告；独立两引擎销售额、取消金额、数量、订单数、客户数、缺失数汇总一致。源文件哈希和行号保留。',
              f"- 原虚构库仍为 {audit['mysql_counts']['original_orders']} 条订单；原2个指标保留，新库8个指标。查询账号只读检查 {audit['reader_select_only']}，未授权HTTP状态 {audit['unauthorized_status']}。",
              '- 来源历史期间为2009-12-01至2011-12-09，首尾年不完整；GBP不是人民币。数据没有人力部门/政策实验，不支持管理政策因果识别。', '',
              '## 复核与使用', '',
              '- 使用说明：`docs/真实零售数据接入.md`；真实数据启动：`start_retail.cmd`。',
              '- 独立金标与SQL：`backend/evaluation/retail_ii_200.json`；生成和请求代码：`tools/retail_benchmark.py`。',
              '- 数据源与哈希：`datasets/uci_online_retail_ii/source_manifest.json`；导入核对：同目录`mysql_import.json`。',
              '- 数据质量：`reports/retail_installation_audit.json`；可执行复核笔记本：`reports/retail_data_quality.ipynb`。',
              '- 软件回归及源包完整性：`reports/主流程验证报告.md`，与真实LLM成绩分开。',
              f"- 留出运行期间应用文件哈希未变：{tested['application_unchanged_during_run']}。题集SHA-256：`{tested['benchmark_sha256']}`。",
              '- 没有实现因果推断、贡献分解或生产人力权限体系；本轮已完成的是真实数据接入和受限问数评测。']
    (reports/'真实零售数据评测报告.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__=='__main__':
    main()
