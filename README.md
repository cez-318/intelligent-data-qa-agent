# 智能问数
- 自然语言问题经字段、取值、指标三路检索后进入结构化查询规划。
- 注册指标由服务端配置编译，不允许模型随意改写业务公式。
- SQL 经过 AST、表列白名单、函数限制、只读约束和 `EXPLAIN` 检查；修复后必须重新校验。
- 支持汇总、分组、排序、多指标、两期比较、完整分组贡献和订单数×客单价两因素分解。
- 缺失期间、零基期、未知指标和不支持结构进入澄清或拒绝路径，不补零、不生成预置答案。
- SSE 流式返回进度、结果、口径、SQL与诊断编号；前端识别断流、非法帧、超时和认证错误。
- 随机实验模块对登记数据计算意向处理效应与多重比较校正区间，和普通观察性问数严格分离。

## 快速开始

### 1. 安装代码依赖

要求 Windows、Python 3.14、Node.js 22.12+、Docker Desktop。

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
Copy-Item .\backend\.env.example .\backend\.env
```

### 2. 填写模型配置并生成本地凭据

在 `backend/.env` 中填写新的 `LLM_API_KEY`。

```powershell
.\.venv\Scripts\python.exe .\tools\configure_local_credentials.py --prepare
```


### 3. 准备容器镜像和 Embedding 模型

`compose.search.yaml` 默认从 `models/bge-large-zh-v1.5` 只读挂载模型。发布包不携带模型权重和 Docker 镜像；请按 [模型目录说明](models/README.md) 准备后再运行：

```powershell
.\start_services.cmd
```

### 4. 准备公开零售数据

发布包不携带大型数据文件。下载、规范化、导入、建索引步骤见 [数据目录说明](datasets/README.md) 和 [真实零售数据接入](docs/真实零售数据接入.md)。完成后运行：

```powershell
.\start_retail.cmd
```

浏览器打开 `http://127.0.0.1:8000`，页面只填写 `DATA_AGENT_API_TOKEN`，不能填写 DeepSeek API Key。

## 目录说明

| 目录或文件 | 作用 |
|---|---|
| `backend/app` | FastAPI 接口、LangGraph 编排、外部依赖客户端与数据库仓储 |
| `backend/improved` | 指标编译、安全校验、诊断、贡献分解、实验统计等增强模块 |
| `backend/conf` | 默认样例与真实零售两个数据配置，包含指标口径和查询白名单 |
| `backend/prompts` | 检索扩展、筛选、查询规划和SQL纠错协议 |
| `backend/evaluation` | 冻结题集、标准答案与哈希；不能为追求分数随意修改 |
| `backend/tests` | 249项后端回归测试及受控测试适配器 |
| `frontend` | Vue 单页应用、实验面板和SSE流解析测试 |
| `tools` | 数据下载、建仓、索引、评测、核算和验收工具 |
| `reports` | 精简后的最新验证结论、运行证据和独立核算笔记本 |
| `docs` | 架构、部署、数据、验收、因果边界、源码导学和面试材料 |
| `compose.*.yaml` | 本机隔离的 MySQL、ES、Qdrant 与 Embedding 服务 |

更详细的逐目录、逐链路说明见 [项目结构与模块说明](docs/项目结构与模块说明.md)。

## 验证结果

- 后端回归：249/249；发布包所选主流程和安全模块语句覆盖率 92.62%。
- 前端流处理测试：10/10；Vite 生产构建通过。
- 当前 DeepSeek 冻结问数评测：开发集 50/50，留出集 150/150。
- 贡献分解：真实 MySQL 固定计划 17/17；在线完整集严格评分 19/20，唯一失败为缺失期澄清格式差异，0 个系统错误。
- 随机实验：64,000 行公开实验数据的4项效应与区间和独立实现一致。


## 验证命令

```powershell
.\verify.cmd
cd .\frontend
npm test
npm run build
```

## 文档入口

- [项目结构与模块说明](docs/项目结构与模块说明.md)：每个目录、模块和请求阶段的职责。
- [源码导学](docs/导学-智能问数.md)：推荐阅读顺序、核心原理和设计取舍。
- [配置与安全](docs/DeepSeek配置说明.md)：模型、令牌、数据库和秘密管理。
- [接入与验收](docs/接入与验收.md)：新数据源接入和上线前检查。
- [真实零售数据接入](docs/真实零售数据接入.md)：106万行公开数据的来源、口径与重建流程。
- [贡献分解与边界](docs/贡献分解与边界.md)：描述性分解算法和非因果边界。
- [随机实验因果评估](docs/随机实验因果评估.md)：实验登记、估计方法和拒答条件。
- [发布内容清单](交付清单.md)：保留、排除和可重新生成内容。


