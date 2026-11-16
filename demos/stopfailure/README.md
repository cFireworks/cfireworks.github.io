# StopFailure 改不了结局

本地脚本。假四种收束：主代理正常说完（`agent_finished`）、用户中断（`user_interrupt`）、接口报错（`api_error`，覆盖 `rate_limit` 和 `authentication_failed`）、工具还在环里（`in_loop`）。

处理器是 `none`、`exit2`、`block`、`additional_context`、`terminal_bel`、`block_bel`、`terminal_csi`、`wrong_field`。另有一只 `hook_type=prompt` 的拒绝，和两只写了 `if` 的钩子。一次只挂一只。

`rate_limit` 的 `error_details` 和 `last_assistant_message` 用 Hooks reference 的例子：`429 Too Many Requests`，`API Error: Rate limit reached`。`authentication_failed` 不填这两个可选字段。专项没给例子，夹具不编。Stop 的 `last_assistant_message` 用专项例子 `I've completed the refactoring. Here's a summary...`。第一次停轮的 `stop_hook_active` 设为 false。页上那份例子是已经在续轮，所以是 true。夹具不模拟第二次，也不模拟八次连拦。

`block` 的 `reason` 和 `additionalContext` 用 Stop 决策节的例子句子。exit 2 的 stderr 是夹具自己的「测试还没绿」。页上只写 stderr 走「为什么要继续」的路径。

`stop_fired` 表示 Stop 到了。`stop_failure_fired` 表示 StopFailure 到了。`handler_ran` 表示处理器跑了。`continued=1` 只出现在 Stop 的 exit 2、`decision: "block"` 或 `additionalContext`。StopFailure 上这三样都是 `continued=0`、`output_ignored=1`。`terminal_sequence_kept=1` 只表示夹具收下了一个裸 BEL，不表示续轮。CSI 颜色序列按页上的拒绝名单记成 `terminal_sequence_kept=0`。夹具没有通用 OSC 解析器，也不写终端。

`wrong_field` 把非空的 `last_assistant_message` 当成模型已经回话。例子字符串会触发这个误判。夹具标 `wrong_field_semantics=1`，`judged_done=0`，不续轮。

`matcher=rate_limit` 只命中 `error=rate_limit`。`rate_limit|authentication_failed` 走精确匹配，`|` 分隔备选项。带逗号或连字符的写法标成 `matcher_path=regex`、`match_result=not_simulated`。夹具不算正则。给 Stop 写的 matcher 标成 `ignored`：没有 matcher 支持的事件会静默忽略这个字段，钩子仍跑。`if` 写在 Stop 或 StopFailure 上时 `if_blocked=1`、`handler_ran=0`。参考页说 `if` 只在五只工具事件上求值，其余事件写了 `if` 的钩子 never runs。夹具不排 matcher 和 `if` 的先后。

`prompt_refused=1` 表示夹具拒绝在 StopFailure 上跑 prompt 评估器。支持列表没有这个类型。运行时配了之后是跳过还是报错，专项没有 PermissionRequest 那种 skips it 的句子。夹具不断言那一句。

`tool_failure_in_loop` 是「还在工具环里」的时刻。`turn_end=open`。不是说工具失败之后永远等不到 Stop。模型后来正常说完，仍走 Stop。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks#stopfailure) 的 Stop / StopFailure 小节、matcher 规则、退出码表、Decision control 总表、`terminalSequence` 和 Prompt-based hooks 的支持列表。

```bash
python3 demos/stopfailure/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `agent_finished_allow` | 正常说完，没拦，这一轮可以停 |
| `agent_finished_exit2` | Stop 的 exit 2 续轮 |
| `agent_finished_block` | `decision: "block"` 续轮 |
| `agent_finished_context` | `additionalContext` 续轮 |
| `agent_finished_matcher` | Stop 上的 matcher 被忽略，闸仍跑 |
| `stop_if_never_runs` | Stop 上写了 `if`，闸不跑 |
| `user_interrupt` | 用户中断，两只都不来 |
| `tool_failure_in_loop` | 工具还在环里，两只都不来 |
| `rate_limit_exit2` | `rate_limit` 走 StopFailure，exit 2 被丢掉 |
| `auth_block` | `authentication_failed` 走 StopFailure，block 被丢掉 |
| `rate_limit_context` | `additionalContext` 不被收下 |
| `rate_limit_bell` | 裸 BEL 留下，不续轮 |
| `rate_limit_block_bell` | block 加 BEL，仍不续轮 |
| `rate_limit_csi` | CSI 序列被拒绝 |
| `rate_limit_wrong_field` | 错误字符串被误当成模型回复 |
| `matcher_miss` | `rate_limit` 对不上 `authentication_failed` |
| `matcher_pipe` | `\|` 分隔的精确匹配命中 |
| `matcher_comma` | 逗号走上正则路径，不算结果 |
| `matcher_hyphen` | 连字符走上正则路径，不算结果 |
| `prompt_refused` | prompt 类型不在支持列表里 |
| `failure_if_never_runs` | StopFailure 上写了 `if`，钩子不跑 |
