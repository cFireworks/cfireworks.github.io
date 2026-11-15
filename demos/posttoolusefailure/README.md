# PostToolUseFailure 改不了错误原文

本地脚本。假六种到来：未知工具名（`unknown_tool`）、schema 或工具侧校验失败（`schema_validation`）、权限拒绝（`permission_deny`）、用户取消正在跑的工具（`user_cancel_running`）、工具自己抛错（`tool_threw`）、MCP 工具返回错误结果（`mcp_error_result`）。另有一条 shell 进程没启动起来（`shell_not_started`）。

处理器是 `exit2`、`exit0_stderr`、`additional_context`、`updated_tool_output`、`updated_mcp_tool_output`、`decision_block`、`prompt_ok_false`、`none`。一次只挂一只。

`tool_threw` 的 `tool_input.command` 和 `error` 照着 Hooks reference 的例子：`npm test`，`Exit code 1` 后面接 `Error: Cannot find module 'express'`，`is_interrupt` 为 false，`duration_ms` 为 4187。输入里没有 `tool_response`。MCP 那条的工具名、`error` 字符串是夹具自己的。专项只说错误结果会让事件开火，没给例子。`mcp_server` 只用 PreToolUse 点名的 `name` 和 `source`。裸失败那句原文专项没引用，夹具用本地字符串，首行不是 `Exit code N`。

`failure_fired` 表示这只事件到了。`handler_ran` 表示处理器跑了。未知工具名和校验失败，`pre_fired=0`、`failure_fired=0`、`tool_use_error=1`。权限拒绝，`pre_fired=1`、`failure_fired=0`。取消正在跑的工具，`failure_fired=0`、`interrupt_on_tool_result=1`。夹具按「工具已经在跑，PreToolUse 的时刻已经过去」把 `pre_fired` 记成 1。专项没有单独写取消时这只前置事件来不来。

开火之后，`exit2` 是 `failed_still=1`、`stderr_for_model=1`、`error_rewritten=0`。`exit0_stderr` 的 `stderr_for_model=0`。`additional_context` 是 `context_attached=1`，`error` 仍是原文。`updatedToolOutput` 和 `updatedMCPToolOutput` 的 `rewrite_accepted=0`。`decision_block` 的 `block_specified=0`：专项没写 block 对失败结果做什么，夹具不把它当成改写或撤销。`prompt_ok_false` 两行分别把 `continueOnBlock` 设成 false 和 true，`prompt_reason_as_tool_error=1`、`turn_continues=1`、`continue_on_block_honored=0`。`error_rewritten=0` 只表示没走改写字段。reason 会不会换掉顶层 `error`，专项没写。

`is_interrupt: true` 且仍然开火的案例，专项没有列出。夹具拒绝构造。人手按 Esc 的中断原文也不编。

空 matcher 在输出里写成 `matcher=empty`。非空只按 `|` 切。不模拟逗号，也不模拟正则。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks#posttoolusefailure) 的 PostToolUseFailure 小节、退出码表、Decision control 总表和 Prompt-based hooks 的 per-event 行为。

```bash
python3 demos/posttoolusefailure/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `unknown_tool` | 未知工具名，`tool_use_error`，两只钩子都不来 |
| `schema_validation` | 校验没过，exit 2 打在这只事件上等于没挂 |
| `permission_deny` | `PreToolUse` 已发生，本事件不来 |
| `user_cancel_running` | 取消正在跑的工具，本事件不来 |
| `tool_threw_exit2` | 失败已成立，stderr 交给模型，`error` 不改 |
| `tool_threw_exit0_stderr` | exit 0 的 stderr 模型看不见 |
| `tool_threw_context` | `additionalContext` 附上，`error_rewritten=0` |
| `tool_threw_updated` | 误用 `updatedToolOutput`，不算出改写 |
| `tool_threw_block` | `block_specified=0`，不当成改写或撤销 |
| `tool_threw_prompt_off` | `ok: false`，`continueOnBlock` 为 false |
| `tool_threw_prompt_on` | 同一句，开关为 true 也不改结果 |
| `tool_threw_matcher_miss` | 事件到了，`Edit\|Write` 对不上 `Bash` |
| `mcp_error_updated` | MCP 错误结果会开火，误用 `updatedMCPToolOutput` |
| `shell_not_started` | 没有 exit-code 行，其余当展示文本 |
| `tool_threw_none` | 什么都不交，失败仍成立 |
