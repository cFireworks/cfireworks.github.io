# 进站结果的模型视图

本地脚本。工具已经成功。伪种类是 `builtin`、`mcp`。伪处理器是 `none`、`replace`、`annotate`、`block_only`、`bad_shape`。假凭证是 `AKIA_EXAMPLE_NOT_REAL` 和 `sk-example-not-a-real-key`。

`replace` 交回参考页那种 Bash 对象，模型视图里没有这两段字符串，遥测里仍有。`annotate` 和 `block_only` 把提醒或 reason 放在旁边，原始输出还在。内置工具的 `bad_shape` 是一段字符串，替换被忽略。MCP 不做这层校验。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks) 的 PostToolUse 决策控制。

```bash
python3 demos/updatedtooloutput-redaction/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `replace` | 内置工具，`updatedToolOutput` 形状通过 |
| `annotate` | 只追加 `additionalContext` |
| `block_only` | 只给顶层 `decision: "block"` |
| `bad_shape` | 内置工具，替换值是字符串 |
| `none` | 什么都不交 |

`replace_and_note`、`block_and_replace`、`mcp_bad_shape`、`mcp_replace` 只在断言里。追加和 block 与一份通过的替换同时出现时，模型视图仍是替换后的。MCP 的字符串替换不会被形状校验退回。
