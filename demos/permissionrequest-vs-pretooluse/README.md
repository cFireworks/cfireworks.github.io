# 弹窗闸和每刀闸

本地脚本。伪事件是 `pre_tool`、`permission_request`。伪处理器是 `none`、`exit2`、`decision_deny`、`permission_decision_deny`。`dialog` 表示马上要弹窗，或走到没法弹窗就要自动拒绝的那条。

`permission_request` 加上 exit 2，结局是 `not_blocked`。同一只事件加上 `decision_deny`，结局是 `blocked`。`pre_tool` 加上 exit 2，结局是 `blocked`，`PermissionRequest` 记成 `never_fired`。不弹窗时，即便配了 `decision_deny`，弹窗钩子也不触发。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。退出码语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks)。

```bash
python3 demos/permissionrequest-vs-pretooluse/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `pr_exit2` | 要弹窗，`PermissionRequest` 交 exit 2 |
| `pr_deny` | 要弹窗，`decision.behavior` 为 deny |
| `pre_exit2` | `PreToolUse` exit 2。弹窗钩子不触发 |
| `no_dialog` | 不弹窗。配了 `decision_deny` 也不会跑 |
| `pre_deny` | `PreToolUse` 的 `permissionDecision` 为 deny |

`wrong_shape`、`wrong_shape_pre`、`no_dialog_pre`、`pr_silent` 只在断言里。填错形状不会变成 `blocked`。不弹窗时，`PreToolUse` 的 exit 2 仍然拦住调用。
