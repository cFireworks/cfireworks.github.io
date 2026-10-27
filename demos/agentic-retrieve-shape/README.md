# AgenticRetrieveStream 的两种请求形状

本地对照，不连接 AWS，也不包含凭证。

- `gateway_tools_call.json`：AgentCore Gateway 文档里的 `tools/call` 形状。Agent 只提交 `messages`。工具名 `managed-kb___AgenticRetrieveStream` 来自该文档的示例，知识库 id 由 target 绑定。
- `agentic_retrieve_request.json`：`AgenticRetrieveStream` API 参考里的直接调用形状，改成两个占位 retriever，用来表示 2026-07-23 博文里「一次请求、多库、靠 description 分流」。`KB_*_PLACEHOLDER` 不是真实 id。
- CDK 样本（2026-10-26）走的是前一种的多 target 版本：每个托管库一个工具。本目录把两种形状放在一起，是为了看清选择发生在哪一层。

```bash
python3 demos/agentic-retrieve-shape/show_shape.py
```

字段以 2026-10-27 读到的文档为准。文档改了，先改 JSON，再跑脚本。
