# 配置平面闸挂在哪一只事件上

本地脚本。假一次会话中途的配置变更：`project_settings`、`skills`、`policy_settings`。处理器是 `exit2`、`block_decision`、`allow_silent`、`none`。hook 对上 source 才跑。没跑起来，新配置照进会话。

`exit2` 和 `block_decision` 在 `project_settings`、`skills`、`local_settings` 上把 `applied` 记成 0。`policy_settings` 上 hook 仍跑，`applied` 仍是 1。`allow_silent` 的 JSON 有 `continue: false` 和 `systemMessage`，没有 `decision`，`applied` 是 1。`none` 什么都不交，`applied` 是 1。每一行的 `ui_notice` 都是 0。

`server_managed_skip` 表示这次刷新不调用 hook。`source=-` 不是参考页上的 matcher 值。装着 `exit2` 也不开火，`hook_fired` 是 0，`applied` 是 1。

`skills_wrong_matcher` 的 matcher 是 `project_settings|local_settings`，来源是 `skills`，`hook_fired` 是 0。`local_settings_narrow_exit2` 用同一条 matcher，`applied` 是 0。`project_if_skipped` 给 ConfigChange 写了 `if`，hook 不开火，`applied` 是 1。

空 matcher 在输出里写成 `matcher=empty`。夹具把它当成对上每个会开火的 source，对应指南里那个记下每一次变更的例子。非空只按 `|` 切。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks#configchange) 的 ConfigChange 小节，和 [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide) 里审计配置变更那一节。

```bash
python3 demos/configchange-gate/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `project_settings_exit2` | exit 2 挂在项目 settings |
| `project_settings_block_decision` | 顶层 `decision: "block"` |
| `project_settings_allow_silent` | 没有 `decision`。`continue` 和 `systemMessage` 不拦 |
| `project_settings_none` | 什么都不交 |
| `skills_exit2` | 技能文件，exit 2 |
| `skills_block_decision` | 技能文件，顶层 `decision: "block"` |
| `policy_settings_exit2` | exit 2 被忽略，hook 仍跑 |
| `policy_settings_block_decision` | `decision: "block"` 被忽略，hook 仍跑 |
| `server_managed_skip` | 不调用 hook |
| `skills_wrong_matcher` | matcher 是项目侧，来源是 skills |
| `local_settings_narrow_exit2` | 同一条 matcher 对上 local settings |
| `project_if_skipped` | ConfigChange 上写了 `if`，hook 不开火 |
