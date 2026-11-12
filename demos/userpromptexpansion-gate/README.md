# 命令展开这扇门挂在哪一只事件上

本地脚本。假一次打出来的 `/deploy staging`（`slash_command`，`command_name` 为 `deploy`），一次 `/review`，一次 MCP prompt，一次 Claude 调用 `Skill` 工具。处理器是 `upe_exit2`、`upe_block_decision`、`upe_stdout_context`、`ups_exit2`、`pretooluse_skill_only`、`upe_with_if`、`none`。

`/deploy staging` 的参数形状照着参考页的例子填：命令名一段，后面一段进 `command_args`，`prompt` 是打出来的整行。页上的命令名例子是 `example-skill`。`release-note` 是夹具自己的 MCP prompt 名字。它的 `prompt` 文本不冒充页上没给的唤起语法。`command_source` 只在斜杠那条上使用页上的例子值 `plugin`。夹具不靠这个字段做决定。

`upe_exit2` 和 `upe_block_decision` 在 matcher 为 `deploy` 时，把打出来的 `/deploy staging` 记成 `expanded=0`、`model_saw_prompt=0`。同一条 matcher 遇到 `/review`，hook 不开火，展开发生。

`upe_stdout_context` 放行。纯文本 stdout 和 `hookSpecificOutput.additionalContext` 分成两条通道记进模型上下文。一条真实 command hook 的 stdout 要么是纯文本，要么是一份 JSON。夹具分开记，只为断言放行时各自会到。拦住时不记注入。

`ups_exit2` 把 `expanded` 和 `embedded_shell_ran` 都记成 0。这是对 changelog v2.1.299 的模拟：`UserPromptSubmit` 在展开之前跑，拦住则嵌入的 shell 不跑。

`pretooluse_skill_only` 遇到打出来的 `/deploy staging`，`pretooluse_fired=0`，`expanded=1`。同一只处理器遇到模型调用 `Skill`，`pretooluse_fired=1`，工具被拦住，`upe_fired=0`。

`upe_with_if` 把 `if` 写在 `UserPromptExpansion` 上。hook 不跑，展开发生。`none` 展开发生，没有闸。

空 matcher 在输出里写成 `matcher=empty`。夹具把它当成对上每一次 prompt-type 命令，`slash_command` 和 `mcp_prompt` 都算。非空只按 `|` 切。不模拟逗号，也不模拟正则。用不上 matcher 的处理器写成 `matcher=na`。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks#userpromptexpansion) 的 UserPromptExpansion、UserPromptSubmit 小节，和 [v2.1.299](https://github.com/anthropics/claude-code/releases/tag/v2.1.299) 里 UserPromptSubmit 先于展开那一句。

```bash
python3 demos/userpromptexpansion-gate/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `typed_deploy_upe_exit2` | matcher `deploy`，exit 2，展开不发生 |
| `typed_deploy_upe_block_decision` | 顶层 `decision: "block"` |
| `typed_review_upe_exit2` | 同一条 matcher，来的是 `/review` |
| `typed_deploy_upe_stdout_context` | 放行，stdout 和 `additionalContext` 在旁边 |
| `typed_deploy_ups_exit2` | `UserPromptSubmit` exit 2，模拟 v2.1.299 |
| `typed_deploy_pretooluse_skill_only` | 闸只挂在 `Skill` 上，人打了斜杠命令 |
| `skill_tool_pretooluse_skill_only` | 模型调用 `Skill`，exit 2 拦住工具 |
| `typed_deploy_upe_with_if` | `UserPromptExpansion` 上写了 `if` |
| `typed_deploy_none` | 什么都不交 |
| `mcp_prompt_upe_exit2` | MCP prompt，命令名对不上 `deploy` |
| `mcp_prompt_matched_exit2` | MCP prompt，matcher 对上命令名 |
| `mcp_prompt_stdout_context` | 空 matcher，MCP prompt 也放行并注入 |
| `skill_tool_upe_exit2` | 展开闸挂着，来的是工具调用 |
