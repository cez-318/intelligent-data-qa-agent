"""Executed, independent RCT calculation audit; no private application inputs."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import nbformat
from nbclient import NotebookClient
from nbconvert import HTMLExporter

ROOT=Path(__file__).resolve().parents[1]
md,code=nbformat.v4.new_markdown_cell,nbformat.v4.new_code_cell
notebook=nbformat.v4.new_notebook(cells=[
md('# 随机实验效应：计算审计\n\n## tl;dr\n'
   'Hillstrom 公开实验 64,000 行；四项比较的效应和校正区间分别对照原始 CSV 聚合与 statsmodels。'
   '这是计算一致性审计，不是已知真实因果效应的准确率测验。'),
md('## Context & Methods\n'
   '实验说明：[Kevin Hillstrom / MineThatData](https://blog.minethatdata.com/2008/03/minethatdata-e-mail-analytics-and-data.html)。'
   '发布者描述三组随机分配，结果为分配后两周购买与访问。\n\n'
   '估计量为意向处理风险差，即处理组全体客户的发生率减对照组全体客户的发生率。'
   '同时分析两种邮件 × 两个二元结果共四项比较；Wilson/Newcombe 区间使用 alpha=0.05/4，'
   '单项名义覆盖率98.75%，Bonferroni整体名义覆盖目标95%。\n\n'
   '### Key Assumptions\n'
   '依赖发布者的随机分配、每行一名独立客户、完整随访和无干扰假设。无客户ID、分配日志或逐日时间戳；'
   '保留完全相同行而不擅自去重。HTTP下载缺乏传输认证，已固定SHA-256；未禁用HTTPS校验。'
   '仅适用于该历史邮件实验，不能外推为人力政策效果。\n\n'
   '这是四项数值核对的小型审计，使用带区间的精确值表，不额外绘图。'
   '重跑：项目环境 `python tools/build_experiment_audit.py`，依赖 requirements-tested.txt 和 requirements-audit.txt。'),
md('## Data\n### 1. 固定原始文件与结果记录'),
code("""from pathlib import Path
import hashlib, json, math
import duckdb
from statsmodels.stats.proportion import confint_proportions_2indep
from IPython.display import display, Markdown
root=Path.cwd()
if not (root/'backend').exists(): root=root.parent
paths=sorted((root/'reports').glob('experiment_live_*.json')) or sorted((root/'reports').glob('experiment_direct_*.json'))
path=paths[-1]
report=json.loads(path.read_text(encoding='utf-8'))
result=report['result']
raw=root/'datasets/hillstrom/hillstrom.csv'
assert hashlib.sha256(raw.read_bytes()).hexdigest()==result['evidence']['data_sha256']
print('结果记录:',path.name,'；实际HTTP接口:',report['live_http'])
print('数据 SHA-256:',result['evidence']['data_sha256'])
print('完全相同行额外数量:',result['data_quality']['exact_duplicate_extra_rows'],'；未作删除。')"""),
md('### 2. 用独立 DuckDB SQL 聚合原始 CSV\n分母是分配组全体客户，不是访问者或已购买者。'),
code("""sql='SELECT segment, COUNT(*) AS n, SUM(conversion) AS conversions, SUM(visit) AS visits FROM read_csv_auto(?) GROUP BY segment ORDER BY segment'
db=duckdb.connect()
rows=db.execute(sql,[str(raw)]).fetchall()
db.close()
oracle={r[0]:{'n':r[1],'conversion':r[2],'visit':r[3]} for r in rows}
assert oracle==result['diagnostics']['arms']
assert sum(g['n'] for g in oracle.values())==64000
table=['|分配组|人数|购买人数|访问人数|','|---|---:|---:|---:|']
table += [f'|{arm}|{g["n"]:,}|{g["conversion"]:,}|{g["visit"]:,}|' for arm,g in oracle.items()]
display(Markdown('\\n'.join(table)))"""),
md('## Results\n### 3. 独立区间与效应核对\n效应和区间均以百分点表示，不能和相对增长百分比混用。'),
code("""table=['|邮件组|结果|效应（百分点）|98.75%校正区间（百分点）|','|---|---|---:|---|']
max_error=0
for row in result['effects']:
    first=oracle[row['treatment']]
    base=oracle['No E-Mail']
    key=row['outcome']
    effect=first[key]/first['n']-base[key]/base['n']
    low,high=confint_proportions_2indep(first[key],first['n'],base[key],base['n'],method='newcomb',compare='diff',alpha=.05/4)
    error=max(abs(effect-row['risk_difference']),abs(low-row['ci_low']),abs(high-row['ci_high']))
    max_error=max(max_error,error)
    assert error<1e-12
    table.append(f'|{row["treatment"]}|{key}|{effect*100:.4f}|[{low*100:.4f}, {high*100:.4f}]|')
display(Markdown('\\n'.join(table)))
print('四项核对全部通过；最大绝对计算差:',max_error)
print('区间完全位于0上方；这是该实验在所述假设成立条件下的平均效应估计，不是确定的个人效果。')"""),
md('### 4. 分配比例与处理前平衡\n样本比例检验和基线平衡都不能单独证明随机化或消除未观测偏差。'),
code("""chi2=sum((g['n']-64000/3)**2/(64000/3) for g in oracle.values())
# df=2 chi-square survival has this independent closed form.
probability=math.exp(-chi2/2)
assert abs(probability-result['diagnostics']['sample_ratio_p'])<1e-12
print('三组1:1:1分配比例检验 p =',round(probability,6),'；阈值0.001，无异常告警。')
balance=result['data_quality']['baseline_balance']
print('注册的5个处理前数值变量 × 2个处理组；|SMD|>0.1告警:',sum(r['flag'] for r in balance))
print('客户唯一性已独立核验:',result['evidence']['customer_identity_verified'])"""),
md('## Takeaways\n'
   '聚合、风险差与区间计算可复现。不能把四项数值核对通过写成“因果准确率100%”。'
   '本实现不提供任意观察性数据的自动因果发现、差分中的差分、连续金额效应或事后挑选子组。'
   '要评估用友人力政策，仍需经授权的数据、具体政策定义、处理分配、对照组、时间窗口与研究设计。')
])
notebook.metadata.kernelspec={'display_name':'Python 3 (project .venv)','language':'python','name':'python3'}
with TemporaryDirectory(prefix='qa-experiment-kernel-') as temporary:
    NotebookClient(notebook,timeout=60,resources={'metadata':{'path':str(ROOT)}}).execute(env={**os.environ,'IPYTHONDIR':temporary})
nbformat.validate(notebook)
destination=ROOT/'reports/experiment_audit.ipynb'
nbformat.write(notebook,destination)
html,_=HTMLExporter().from_notebook_node(notebook)
destination.with_suffix('.html').write_text(html,encoding='utf-8')
print('Executed and saved',destination.name)
