# SessionEnd 留不住会话

本地脚本。按 Hooks reference 的 `SessionEnd` 输入例子、reason 表、退出码表、Decision control、matcher 规则，以及 hooks-guide 的「只在 `/clear` 时开火」和 1.5 秒预算，在本地走一遍。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook，也不是一次真实退出。

`reason` 只使用页上仍会发送的五只：`clear`、`resume`、`logout`、`prompt_input_exit`、`other`。`bypass_permissions_disabled` 标成 `reason_sent=0`、`event_fired=0`。输入 JSON 只用专项例子里的五个字段：`session_id`、`transcript_path`、`cwd`、`hook_event_name`、`reason`。`other` 那一行用例子原文，其余只改 `reason`。

`clear` 的 matcher 命中 `clear`，对不上 `other`。指南说这个 matcher 在普通退出上不开火。夹具用例子里的 `other` 代表这次对不上，不另造一个 reason 字符串，也不列举 `other` 覆盖哪些路径。

逗号和空格仍走精确匹配。连字符是精确字符，不是分隔符。`^clear$` 含有别的字符，标成 `matcher_path=regex`、`match_result=not_simulated`。夹具不算正则。

exit 2 的 stderr 是夹具自己的 `fixture: session already ending`。页上只写 Shows stderr to user only。`decision: "block"` 和 `systemMessage` 记成 `json_discarded=1`。专项写 Claude Code discards their JSON output fields, such as `systemMessage`。`blocks_termination` 在 SessionEnd 上保持 0。

`stop_exit2` 和 `stop_block` 只做最小对照：Stop 上这两只可以 `turn_continued=1`。不重放 11 月 16 日的 StopFailure 套件，也不给 Stop 编一份输入 JSON。

超时数字只用文档：默认 1500 毫秒，单只 settings hook 的 `timeout` 把总体预算抬到与之匹配、上限 60000 毫秒，没写 `timeout` 的 hook 仍是 1500。插件 hook 的 timeout 记 `plugin_raises_budget=0`，它自己的等待记 `plugin_wait_ms=unspecified`。环境变量用页上的例子 `5000`。`rules=before_2.1.268` 时，这个变量只抬 `budget_ms`，没写 `timeout` 的 hook 仍是 1500。普通 command hook 的 600 秒默认被标成 `rejected_600=1`，不抄到这只事件上。

`prompt` 和 `agent` 记成不支持，夹具不跑评估器。`if` 写在这只事件上时 `if_blocked=1`、`handler_ran=0`。`mcp_tool` 记 `waits_for_server=0`。command hook 的调试行记 `debug_duration=absent`，不编一条完整日志。

`async` 没有第三条加时路径。SessionEnd 专项只写了 per-hook `timeout` 和环境变量。夹具不把 `async: true` 算成抬预算。

```bash
python3 demos/sessionend/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `clear_hit` | matcher `clear` 命中 `/clear` |
| `clear_miss_other` | 同一个 matcher 对不上 `other` |
| `resume_hit` | 交互式 `/resume` |
| `logout_hit` | `logout` |
| `prompt_input_exit_hit` | `prompt_input_exit` |
| `pipe_hit` | `clear\|resume` 走精确匹配 |
| `comma_hit` | `clear, resume` 仍是精确匹配 |
| `hyphen_not_separator` | 连字符不切开 |
| `regex_not_simulated` | `^clear$` 走正则，不算结果 |
| `match_all_other` | 省略 matcher 时 `other` 也会跑 |
| `removed_not_sent` | `bypass_permissions_disabled` 不再发送 |
| `removed_matcher_miss` | 拿已删除的值去配 `other`，不命中 |
| `exit2_shows_stderr` | exit 2 只把 stderr 给用户，不拦住终止 |
| `block_discarded` | `decision: "block"` 被丢掉 |
| `system_message_discarded` | `systemMessage` 被丢掉 |
| `stop_exit2` | Stop 的 exit 2 可以续轮 |
| `stop_block` | Stop 的 `decision: "block"` 可以续轮 |
| `budget_default` | 默认预算 1500 毫秒 |
| `budget_per_hook` | settings 里 `timeout: 5` 把预算抬到 5000，没写 timeout 的仍是 1500 |
| `budget_cap_60` | `timeout: 90` 时预算停在 60000 |
| `plugin_no_raise` | 只有插件 hook 的 timeout，预算仍是 1500 |
| `settings_not_plugin` | settings 的 5 秒抬预算，插件的 30 秒不抬 |
| `env_current` | `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS=5000`，没写 timeout 的 hook 也是 5000 |
| `env_before_268` | v2.1.268 之前，同一变量只抬总体预算 |
| `prompt_refused` | 不支持 `prompt` |
| `agent_refused` | 不支持 `agent` |
| `if_never_runs` | 这只事件上的 `if` 让钩子不跑 |
| `http_allowed` | `http` 在支持列表里，仍不拦住终止 |
| `mcp_no_wait` | 观察性事件，不等待仍在连接的 MCP 服务器 |
| `stop_mcp_waits` | Stop 这类能改结果的事件会等仍在连接的服务器。只记旗标，不连服务器 |
