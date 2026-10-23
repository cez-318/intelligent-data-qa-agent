# Embedding 模型目录

`compose.search.yaml` 默认将下面的本地目录只读挂载到 Embedding 容器：

```text
models/bge-large-zh-v1.5/
```

发布包不携带模型权重。请从经过批准的模型源准备完整的 `bge-large-zh-v1.5` 文件，并确保许可证允许当前用途。目录应至少包含模型配置、Tokenizer 和权重文件；具体文件名取决于所使用的模型发布版本。

当前容器镜像为 `ghcr.io/huggingface/text-embeddings-inference:cpu-1.8`，以离线模式运行，应用按 TEI `/embed` 协议访问 `127.0.0.1:18080`。配置的向量维度是 1024，替换模型时必须同步修改 `EMBEDDING_MODEL`、`EMBEDDING_SIZE` 并重建 Qdrant 集合，不能把旧索引与新向量混用。

模型目录只读挂载，不应保存 API Key、日志或数据库文件。若模型放在其他位置，请修改 `compose.search.yaml` 的宿主机路径；不要把个人绝对路径提交到公共仓库。
