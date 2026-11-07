# 批边界的一次注入

本地脚本。假一批三只 Read。`tool_response` 是带行号的字符串。处理器是 `none`、`annotate_batch`、`block_batch`、`misparse_as_object`。

`annotate_batch` 的 `injection_count` 是 1，`PostToolUse` 计 3，`PostToolBatch` 计 1。`block_batch` 把循环记成 `stop_before_next_model`，三刀仍是 `already_ran`。`misparse_as_object` 按对象去读 `stdout`，记成 `non_blocking`，循环继续。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks) 的 PostToolBatch 输入和决策控制。

```bash
python3 demos/posttoolbatch-boundary/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `annotate_batch` | 批末一次 `additionalContext` |
| `block_batch` | 顶层 `decision: "block"` |
| `misparse_as_object` | 把序列化文本当成带 `stdout` 的对象 |
| `none` | 什么都不交 |

`per_tool_annotate` 和 `exit2` 只在断言里。每刀各注一句时次数是 3。exit 2 和 block 一样停在下一轮之前，不撤销已经落地的刀。
