# TeammateIdle 的空闲契约

本地脚本。按 Hooks reference 的 `TeammateIdle` 输入例子、决策控制三条、退出码表、无 matcher 规则、prompt / agent 的 Response schema，以及 Agent SDK 表上的 `onFailure`，在本地走一遍。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不启动 agent team。夹具不是 settings 里的 hook。

输入 JSON 只用专项例子里的字段：`session_id`、`transcript_path`、`cwd`、`permission_mode`、`hook_event_name`、`teammate_name`、`team_name`。不补例子里没有的 `agent_id`。`teammate_name` 的例子值是 `researcher`。另一条分支用的 `fixture-other` 是夹具自己的名字，页上没有这只队友。

`team_name` 出现在例子里，标成弃用。两份不同的 `team_name` 必须得到同一裁决，决策函数不读它。

matcher 写成 `researcher` 时仍然开火。过滤发生在脚本读到 `teammate_name` 之后，不是 matcher。

缺产物时的 stderr 引用参考页 bash 例子的原句。夹具不执行那份脚本，也不检查真实的 `./dist/output.js`。

`continue: false` 和另一只 hook 的 `decision: "block"` 或 exit 2 叠在一起时，队友闲下来，`stopReason` 记进 transcript。同一只输出里同时写 exit 2 和 `continue: false`，标成 `simulated=0`、`note=not_simulated`。

`SessionEnd` 的 exit 2 只记 `stderr_to_user=1`、`blocks_termination=0`。`Stop` 上 exit 2 再加 `continue: false` 只记这一轮结束。不重放 11 月 16 日和 11 月 17 日的套件。

prompt hook 默认 `continueOnBlock` 为 false，队友闲下来，`reason` 记 `reason_in_transcript=1`。设成 true 才把 `reason` 交回去并续工。agent hook 没有这个字段，`ok: false` 按 prompt 的 `continueOnBlock: true` 记成续工。

SDK 的 `onFailure: "block"` 在这只事件上被忽略，`action_goes_ahead=1`，并且 `continues_working=0`。这是 callback 失败，不是 command hook 的 exit 2。Python 回调记 0，TypeScript 记 1。

文件缺失那条 non-blocking 规则、以及 MCP 是否等待仍在连接的服务器，页上没有点名 `TeammateIdle`。这两只记 `simulated=0`、`note=not_named`。

```bash
python3 demos/teammateidle/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `exit2_keeps_working` | exit 2，stderr 当反馈，拦住空闲 |
| `block_keeps_working` | `decision: "block"` 加 `reason`，同样续工 |
| `exit0_goes_idle` | exit 0 放行空闲 |
| `continue_false_overrides_block` | `continue: false` 盖过另一只 block |
| `continue_false_overrides_exit2` | `continue: false` 盖过另一只 exit 2 |
| `matcher_ignored` | matcher 写了队友名，另一只名字仍然开火 |
| `script_branches_on_name` | 脚本读 `teammate_name`，`researcher` 走缺产物的 exit 2 |
| `team_name_ignored` | 两份 `team_name` 裁决相同 |
| `agent_id_absent` | 例子 JSON 没有 `agent_id`，决策不依赖它 |
| `prompt_default_idle` | prompt 默认闲下来 |
| `prompt_continue_on_block` | `continueOnBlock: true` 才续工 |
| `agent_ok_false_keeps` | agent 的 `ok: false` 按续工记 |
| `same_hook_mix_unspecified` | 同一只输出里的 exit 2 与 `continue: false`，不算 |
| `sessionend_exit2` | SessionEnd 的 exit 2 留不住终止 |
| `stop_continue_false` | Stop 上 `continue: false` 结束这一轮 |
| `sdk_on_failure_ignored` | SDK `onFailure: "block"` 被忽略 |
| `file_missing_not_named` | 文件缺失规则没有点名这只事件 |
| `mcp_wait_unspecified` | MCP 等待句没有点名这只事件 |
