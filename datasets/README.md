# 数据目录说明

发布包没有直接携带原始数据和派生中间文件，原因如下：

- UCI Online Retail II 的压缩包、XLSX、规范化 CSV、DuckDB 和 MySQL 导入 CSV 合计超过 500MB，其中多数可由脚本确定性重建。
- Hillstrom CSV 的公开来源页没有给出明确的再分发许可证，因此发布包仅保留下载程序、登记配置和验证报告，不擅自重新分发原始文件。
- 数据文件可能包含公开客户编号等原始字段，不应和代码、密钥一起随意传播。

## UCI Online Retail II

项目固定使用 UCI 数据集页面：`https://archive.ics.uci.edu/dataset/502/online+retail+ii`，DOI `10.24432/C5CG6D`，许可证 CC BY 4.0。

从项目根目录依次执行：

```powershell
.\.venv\Scripts\python.exe .\tools\retail_pipeline.py download
.\.venv\Scripts\python.exe .\tools\retail_pipeline.py prepare
.\.venv\Scripts\python.exe .\tools\load_retail_mysql.py --docker "Docker程序绝对路径" --confirm-new-retail-databases
.\.venv\Scripts\python.exe .\tools\run_retail.py index
```

脚本会创建 `datasets/uci_online_retail_ii`，记录下载地址、SHA-256、行数和数据质量结果。`download` 会验证缓存文件；`prepare` 拒绝覆盖已经存在的规范化结果；数据库导入也要求显式确认，避免误覆盖其他库。

主要生成文件：

| 文件 | 用途 | 是否可重新生成 |
|---|---|---|
| `online_retail_ii.zip` | UCI 官方下载归档 | 可以重新下载 |
| `online_retail_II.xlsx` | 归档中的原始工作簿 | 可以重新解压 |
| `source_manifest.json` | 来源、许可证和文件哈希 | 首次下载生成 |
| `normalized_rows.csv` | 加源行号后的规范化明细 | 可以由XLSX重建 |
| `reference.duckdb` | 独立金标计算仓库 | 可以由CSV重建 |
| `mysql_*.csv` | MySQL 星型模型导入文件 | 可以重新导出 |
| `quality.json` | 数据质量、缺失和重复统计 | 可以重新计算 |

## Hillstrom 随机邮件实验

执行：

```powershell
.\.venv\Scripts\python.exe .\tools\fetch_hillstrom.py
```

脚本会创建 `datasets/hillstrom/hillstrom.csv` 与 `manifest.json`。登记文件 `backend/conf/experiments.json` 只允许预先声明的数据文件、处理组、对照组和结果字段，网页请求不能提交任意文件路径。

来源使用 HTTP，发布者未提供可独立验证的数字签名；项目用 SHA-256 固定本地下载版本，但这不等于证明发布者真实性。若公开下载不可用，应从合法来源人工取得同一数据并核对哈希，不要绕过证书或下载校验。

## 不应放入数据目录的内容

- 公司生产人力数据、个人身份信息或未经批准的脱敏数据。
- `.env`、访问令牌、数据库密码和 API Key。
- 临时下载文件、数据库备份和 Docker 卷导出。
- 为提高评测分数而修改过的标准答案或题集。
