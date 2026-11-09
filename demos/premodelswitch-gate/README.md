# 模型身份闸挂在哪一只事件上

本地脚本。假一次「用户或客户端请求切到目标模型」：先 `PreModelSwitch`，没拦住才把模型记成 `to_model`，再走 `PostModelSwitch`。另假一条 resume 自切：Pre 不调用，只走 Post。

请求路径上的处理器是 `pre_exit2`、`pre_deny_json`、`pre_block_decision`、`pre_timeout_sim`、`post_exit2`、`post_inject_nested`、`post_inject_toplevel`、`none`。`resume_auto` 假设 settings 里装着 `pre_exit2`，这条路径仍不调用它。

`pre_exit2`、`pre_deny_json`、`pre_block_decision`、`pre_timeout_sim` 的 `switch` 是 `blocked`，模型留在 `from_model`。`post_exit2` 的 `switch` 是 `applied`，`notice` 是 `user_only`。`post_inject_nested` 的 `injection` 是 1，`model` 已是 `to_model`。`post_inject_toplevel` 的 `injection` 是 0。`resume_auto` 的 `pre_fired` 是 0，`post_fired` 是 1，`switch` 是 `applied`。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks) 的 PreModelSwitch / PostModelSwitch 小节，和 [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide) 里 `permissionDecision` 与顶层字段会被丢掉的说明。

```bash
python3 demos/premodelswitch-gate/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `pre_exit2` | exit 2 挂在请求切换之前 |
| `pre_deny_json` | exit 0，`permissionDecision: "deny"` 在 `hookSpecificOutput` 里 |
| `pre_block_decision` | exit 0，顶层 `decision: "block"` |
| `pre_timeout_sim` | Pre 到点取消。输出里的 allow 丢掉，切换仍取消 |
| `post_exit2` | exit 2 挂在已经切完之后 |
| `post_inject_nested` | `additionalContext` 在 `hookSpecificOutput` 里 |
| `post_inject_toplevel` | 同名字段写在 JSON 顶层 |
| `none` | 什么都不交 |
| `resume_auto` | 运行时自己把模型拨回去，Pre 不开火 |
