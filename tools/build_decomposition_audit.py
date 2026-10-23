"""Create and execute an offline audit companion; never reads credentials."""
from pathlib import Path
import nbformat
from nbclient import NotebookClient
from nbconvert import HTMLExporter

ROOT = Path(__file__).resolve().parents[1]
md, code = nbformat.v4.new_markdown_cell, nbformat.v4.new_code_cell
notebook = nbformat.v4.new_notebook(cells=[
    md('# 增长贡献分解：可复查核算记录\n\n## tl;dr\n'
       '本记录重新执行冻结测试集中的原始数据 SQL，并核对销售变化与分组贡献守恒。'
       '真实 MySQL 的受控计划测试为 17/17；在线自然语言测试另列，不混称准确率。'
       '这不是政策因果分析。'),
    md('## Context & Methods\n'
       '来源：[UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii)。'
       '输入为已下载的 1,067,371 行历史数据，不重新抓取、不读取生产凭据。金额单位 GBP。\n\n'
       '### Key Assumptions\n'
       '正数量、正单价、非 C 开头且非空发票的行计入销售额；重复行保留。'
       '完整分组与独立总额一致后，单期未出现的组在此封闭快照中按零处理；整期无记录不补零。'
       '订单数与平均订单金额的交互项采用两种替换顺序取平均。\n\n'
       '环境：项目 .venv，安装 duckdb、nbformat、nbclient、nbconvert、ipykernel。'
       '从项目根目录执行 `python tools/build_decomposition_audit.py` 可重建。'
       '本文件是小规模核算审计，精确值和守恒检查用表格呈现，不额外绘图。'),
    md('## Data\n### 1. 加载已冻结输入与证据'),
    code("""from pathlib import Path
from decimal import Decimal, localcontext
import hashlib, json
import duckdb
from IPython.display import display, Markdown
root = Path.cwd()
if not (root / 'backend').exists():
    root = root.parent
benchmark_path = root / 'backend/evaluation/decomposition_v1.json'
benchmark = json.loads(benchmark_path.read_text(encoding='utf-8'))
assert hashlib.sha256(benchmark_path.read_bytes()).hexdigest() == benchmark_path.with_suffix('.sha256').read_text().strip()
db = duckdb.connect(str(root / 'datasets/uci_online_retail_ii/reference.duckdb'), read_only=True)
assert db.execute('SELECT COUNT(*) FROM raw_lines').fetchone()[0] == 1067371
print('冻结案例:', len(benchmark['cases']), '；原始行数: 1,067,371')
print('冻结文件 SHA-256:', hashlib.sha256(benchmark_path.read_bytes()).hexdigest())"""),
    md('## Results\n### 2. 重跑独立原始行 SQL\n'
       '只执行冻结文件中已有的 SELECT；不使用应用层的派生销售金额字段或分解函数。'),
    code("""checked = 0
for case in benchmark['cases']:
    if 'gold' not in case:
        continue
    values = []
    for query in case['gold_queries']:
        assert query['sql'].lstrip().upper().startswith('SELECT')
        cursor = db.execute(query['sql'], query['params'])
        columns = [c[0] for c in cursor.description]
        values.append([dict(zip(columns, row)) for row in cursor.fetchall()])
    current, previous = values[0][0], values[1][0]
    revenue1, revenue0 = current['SALES_AMOUNT'], previous['SALES_AMOUNT']
    assert revenue1 == Decimal(case['gold']['current'])
    assert revenue0 == Decimal(case['gold']['previous'])
    if case['kind'] == 'segments':
        assert sum(row['SALES_AMOUNT'] for row in values[2]) == revenue1
        assert sum(row['SALES_AMOUNT'] for row in values[3]) == revenue0
        assert sum(Decimal(row['difference']) for row in case['gold']['groups']) == revenue1 - revenue0
    else:
        with localcontext() as ctx:
            ctx.prec = 50
            n1, n0 = Decimal(current['ORDER_COUNT']), Decimal(previous['ORDER_COUNT'])
            count_effect = ((n1 * revenue0 / n0 - revenue0) + (revenue1 - n0 * revenue1 / n1)) / 2
            value_effect = ((n0 * revenue1 / n1 - revenue0) + (revenue1 - n1 * revenue0 / n0)) / 2
            assert abs(count_effect + value_effect - (revenue1 - revenue0)) < Decimal('0.000001')
            assert abs(count_effect - Decimal(case['gold']['order_count_effect'])) < Decimal('0.000001')
    checked += 1
db.close()
print(f'{checked} 个有两期有效数据的数值案例已重算，全部守恒。')"""),
    md('### 3. 同一比较期的完整分组与两因素核对\n2011 年第一季度相对 2010 年第一季度；完整数据范围内全体客户，GBP。'),
    code("""country = benchmark['cases'][0]['gold']
factors = benchmark['cases'][8]['gold']
assert country['difference'] == factors['difference']
top = country['groups'][:5]
remainder = sum(Decimal(r['difference']) for r in country['groups'][5:])
lines = ['| 国家 / 其余 | 销售额变化（GBP） |', '|---|---:|']
lines += [f"| {r['group']} | {Decimal(r['difference']):,.2f} |" for r in top]
lines += [f'| 其余 {len(country["groups"])-5} 组 | {remainder:,.2f} |',
          f'| 全部变化 | {Decimal(country["difference"]):,.2f} |']
display(Markdown('\\n'.join(lines)))
display(Markdown('| 两因素 | 贡献（GBP） |\\n|---|---:|\\n'
    + f'| 订单数 | {Decimal(factors["order_count_effect"]):,.2f} |\\n'
    + f'| 平均订单金额 | {Decimal(factors["average_order_value_effect"]):,.2f} |'))
print('完整国家分组:',len(country['groups']), '；表格仅显示到分，计算使用未四舍五入值。')"""),
    md('### 4. 各轮测试分开呈现\n失败和复测都保留。复测不再视为新的盲测；开发集与留出集共享问题模板。'),
    code("""direct = json.loads((root / 'reports/decomposition_direct.json').read_text(encoding='utf-8'))
print('受控计划 / 真实 MySQL:', sum(c['passed'] for c in direct['cases']), '/', len(direct['cases']))
for path in sorted((root / 'reports').glob('decomposition_live_*.json')):
    report = json.loads(path.read_text(encoding='utf-8'))
    print(path.name, f"{report['passed']}/{report['completed']}", '应用代码运行中未变:', report['application_unchanged_during_run'])
    print('未通过:', ', '.join(c['id'] for c in report['cases'] if not c['passed']) or '无')"""),
    md('## Takeaways\n'
       '可证明的是：在给定数据、时间、筛选和指标定义下，完整分组与两因素的贡献能还原总变化。'
       '不能证明培训、薪酬或管理政策带来了增量。客单价包含商品组合变化，不等于纯价格效应。'
       '在线问数还取决于模型理解与各依赖服务，不能用受控计划的数值通过率替代自然语言端到端通过率。'
       '未来因果分析需要干预时间、处理组/对照组与前后期结果，并做混杂因素、平行趋势或随机分配等检验。'),
])
notebook.metadata.kernelspec = {'display_name':'Python 3 (project .venv)', 'language':'python', 'name':'python3'}
NotebookClient(notebook, timeout=120, resources={'metadata':{'path':str(ROOT)}}).execute()
nbformat.validate(notebook)
destination = ROOT / 'reports/decomposition_audit.ipynb'
nbformat.write(notebook, destination)
html, _ = HTMLExporter().from_notebook_node(notebook)
destination.with_suffix('.html').write_text(html, encoding='utf-8')
print('Executed and saved:', destination.name)
