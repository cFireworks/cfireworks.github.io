# PermissionDenied 不是放行

本地脚本。假五种到来：手动拒绝弹窗（`manual_deny`）、`PreToolUse` 拦住（`pretooluse_block`）、`deny` 规则命中（`deny_rule`）、auto 分类器给出裁决后拒绝（`auto_classifier_deny`）、分类器没有裁决就拒绝（`no_verdict_deny`）。另有一条分类器模型不可用（`classifier_unavailable`）。

处理器是 `pd_exit2`、`pd_retry_true`、`pd_retry_false`、`pd_no_json`、`pd_permission_decision_allow`、`pd_behavior_allow`、`pd_decision_allow`、`pd_audit`、`pd_prompt_discarded`、`none`。一次只挂一只。

分类器那条的 `tool_input.command` 和 `reason` 照着 Hooks reference 的例子：`rm -rf /tmp/build`，`[Irreversible Local Destruction]`。无裁决的 `reason` 只用专项规定的开头，不把错误页破折号后面的半句拼进去。模型不可用的 `reason` 是固定文本 `Classifier unavailable`，不是错误页那句 `temporarily unavailable`。

`pd_fired` 表示这只事件到了。`handler_ran` 表示处理器跑了。手动拒绝、`PreToolUse` 拦住、`deny` 规则命中，`pd_fired=0`。matcher 写成 `Bash`、工具是 `Edit` 时，事件仍到，处理器不跑。

`pd_exit2` 有 stderr，`stderr_applied=0`，`treated_as_allow=0`。`pd_retry_true` 在有裁决的拒绝上是 `may_retry=1`、`denial_reversed=0`。同一份 JSON 打在无裁决上，`retry_ignored=1`，`may_retry=0`。`retry: false`、无 JSON、`permissionDecision: "allow"`、`decision.behavior: "allow"`、顶层 `decision: "allow"`，都不改判。`model_keeps_original=1` 表示原拒绝消息还在。`may_retry=1` 只表示会另加一句。那句原文页上没给，夹具不编。

`classifier_unavailable` 只和 `pd_audit` 组合。`retry: true` 对这句固定文本是忽略还是收下，专项没有写，夹具拒绝这种组合。

`pd_prompt_discarded` 表示 prompt 钩子跑了，输出被丢掉，`may_retry=0`。`post_failure_fired` 始终是 0。人手在 Recently blocked 按 `r` 不在这个脚本里。

空 matcher 在输出里写成 `matcher=empty`。非空只按 `|` 切。不模拟逗号，也不模拟正则。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks#permissiondenied) 的 PermissionDenied 小节、退出码表和 Decision control 总表。

```bash
python3 demos/permissiondenied-retry/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `manual_deny_retry_true` | 手动拒绝，事件不开火，`retry: true` 没人收 |
| `pretooluse_block_exit2` | `PreToolUse` 已经拦住，exit 2 打在这只事件上等于没挂 |
| `deny_rule_behavior_allow` | deny 规则命中，`decision.behavior: "allow"` 不会跑 |
| `auto_exit2` | 有裁决的拒绝，exit 2，stderr 忽略，拒绝仍成立 |
| `auto_retry_true` | `may_retry=1`，`denial_reversed=0` |
| `no_verdict_retry_true` | `retry_ignored=1`，拒绝仍成立 |
| `auto_retry_false` | `retry: false`，模型侧保持原拒绝消息 |
| `auto_no_json` | 没有 JSON，同样保持原拒绝消息 |
| `no_verdict_no_json` | 无裁决，又没有 JSON |
| `no_verdict_exit2` | 无裁决上的 exit 2，也不放行 |
| `auto_permission_decision_allow` | 填了 `permissionDecision: "allow"` |
| `auto_behavior_allow` | 填了 `decision.behavior: "allow"` |
| `auto_decision_allow` | 顶层 `decision: "allow"` |
| `auto_audit` | 记下例子里的 command 和方括号 reason |
| `no_verdict_audit` | reason 只有专项那个开头 |
| `unavailable_audit` | reason 是 `Classifier unavailable` |
| `auto_prompt_discarded` | prompt 钩子的输出被丢掉 |
| `auto_edit_matcher_bash` | 事件到了，`Bash` matcher 对不上 `Edit` |
| `auto_none` | 什么都不交，拒绝仍成立 |
