# TaskCreated 与 TaskCompleted 的创建 / 勾完契约

本地脚本。按 Hooks reference 的 `TaskCreated` / `TaskCompleted` 输入例子、退出码表、Decision control、`continue: false` 在两条开火点上的不同写法、文件缺失那条 non-blocking 规则、`onFailure` 名单，以及 prompt / agent 的 Response schema，在本地走一遍。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不启动真实 Task 工具，不启动 agent team。夹具不是 settings 里的 hook，也不跑页上那份 `npm test`。

`TaskCreated` 的例子字段没有 `permission_mode`，也没有 `agent_id`。`TaskCompleted` 的例子多一个 `permission_mode: "default"`。`team_name` 按页上的 Deprecated 记。`agent_id` 可能缺席，版本记成 v2.1.290。

exit 2 的 stderr 引用两份 bash 例子里的原句。`decision: "block"` 的 `reason`，以及队友收工时的 `stopReason`，是夹具自己的句子，页上的 JSON 写成 `"..."`。

`continue: false` 和 exit 2 写在同一只 `TaskCompleted` 钩上、又是队友收工路径时，标成 `simulated=0`、`note=same_output_not_stated`。页上写的是「另一只 hook 已经 block」。另一只 hook 的两格（exit 2 和 `decision: "block"`）照样算。

文件缺失那条点了名 `TaskCompleted`，没有点名 `TaskCreated`。创建钩上同样的 stderr 仍按回滚走。

指南的 no-matcher 行包含 `CwdChanged`。参考页把 `CwdChanged` 单独成行，合并行里没有它。夹具记下分行，不把两页收成第三张表。

```bash
python3 demos/taskcreated-completed/run_demo.py
```

通过时最后一行是 `result=pass`。
