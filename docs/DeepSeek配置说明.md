# DeepSeek与本机服务配置

发布包不包含 DeepSeek 密钥、本机令牌或数据库密码。先将 `backend/.env.example` 复制为 `backend/.env`，填写新申请的 DeepSeek 密钥，再运行 `tools/configure_local_credentials.py --prepare` 生成本地令牌和数据库密码。不要把 `.env` 或 `.secrets` 提交 Git。

已创建实际生效的 `backend/.env`，不是只修改示例文件。默认接入DeepSeek官方Chat Completions API：`https://api.deepseek.com`，模型`deepseek-flash`。默认`thinking=disabled`，用于当前多次模型调用的问数流程；如启用深度思考，需要重新评估单次20秒/全流程60秒的超时预算。

官方依据（核对日期2026-09-26）：[模型名与接口](https://api-docs.deepseek.com/)、[思考模式参数](https://api-docs.deepseek.com/guides/thinking_mode/)。不强制JSON-object模式，因为部分检索节点需要返回JSON数组。

## 配置项说明

| `.env`变量 | 填什么 |
|---|---|
| LLM_API_KEY | 使用者自行填写；只在本地保存，不是网页登录密码 |
| DATA_AGENT_API_TOKEN | 已自动生成；网页“服务访问凭据”填同一值；不要复用API Key |
| META_DB_PASSWORD | 已生成并为独立MySQL的metadata_owner账号设置 |
| DW_DB_PASSWORD | 已生成并为独立MySQL的qa_readonly账号设置 |

地址、端口、库名、索引、向量维度在模板中提供本地默认值。填写`.env`不会创建数据库账号，也不会更改数据库密码，账号密码必须与实际服务一致。密码允许包含`=`；含`#`会保留为密码内容，因此不要在值末尾追加行内注释。

## 已设定的服务

| 服务 | 地址/配置 |
|---|---|
| 应用 | http://127.0.0.1:8000 |
| 元数据库 | 127.0.0.1:13306，库meta，用户metadata_owner |
| 只读数据仓库 | 127.0.0.1:13306，库dw，用户qa_readonly |
| Elasticsearch | 127.0.0.1:19200，索引column_values |
| Qdrant | 127.0.0.1:16333，向量维度1024 |
| Embedding | 127.0.0.1:18080，BGE-large-zh-v1.5/TEI，本地CPU |

DeepSeek密钥只负责大模型，不能代替Embedding、MySQL、ES或Qdrant。优化版独立MySQL、ES、Qdrant、Embedding均已启动并实连验证。Embedding走本地TEI `/embed`，使用已有模型的只读挂载，不向云端发送向量请求。

## 填完后

1. 启动Docker Desktop，执行根目录`start_services.cmd`，等待向量模型启动；当前测试库和索引已经初始化，不必反复导入。
2. 关闭之前运行的后端窗口，再执行根目录`start_app.cmd`，使新配置生效。
3. 打开应用，填入DATA_AGENT_API_TOKEN，刷新状态并验证问题。

`.gitignore`已配置排除本地密钥文件。离线回归测试不请求DeepSeek；真实模型评测会产生费用，精确金额以控制台账单为准。正式使用前确认检索样例、表结构和用户问题允许发送至DeepSeek；不要直接使用未经批准的人力个人信息。任何曾在聊天、截图或日志中出现的密钥都应先撤销并轮换。
