# SubagentStart 与 SubagentStop 的开工 / 收工契约

本地脚本。按 Hooks reference 的 `SubagentStart` / `SubagentStop` 输入例子、matcher 规则、退出码表、Decision control、`continue: false` 与 exit 2 的优先关系，以及 prompt / agent 的类型名单和 Response schema，在本地走一遍。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不启动子代理，不启动 agent team。夹具不是 settings 里的 hook。

`SubagentStart` 的例子字段只有 `session_id`、`transcript_path`、`cwd`、`hook_event_name`、`agent_id`、`agent_type`。不补例子里没有的 `permission_mode`。`additionalContext` 引用专项 JSON 里的原句 `Follow security guidelines for this task`。

`SubagentStop` 的例子带 `stop_hook_active`、`agent_transcript_path`、`last_assistant_message`，以及空的 `background_tasks` 和 `session_crons`。两份数组记成父会话作用域，决策不读它们。

exit 2 记在子代理自己的 transcript，不进父会话，Claude 看不见，开工继续。同一份子代理上下文里还持有先前那份拷贝时，不再注入。把 `compacted` 标上之后，下一轮再注入。

同一份 `SubagentStop` 输出里，`continue: false` 和 exit 2 写在一起，子代理停止，`precedence=1`。另一只 hook 已经 exit 2、这一只再写 `continue: false`，标成 `simulated=0`、`note=other_hook_not_stated`。页上那句「即使另一只已经 block」写在 `TeammateIdle`，不抄过来。

文件缺失那条 non-blocking 规则点了名 `SubagentStop`。stdout 为空、stderr 含 `No such file or directory`、exit 2，记成放行停止。

未锚点的 `my-plugin:reviewer` 会命中 `my-plugin:reviewer-extra`。`^my-plugin:reviewer$` 不会。空 `agent_type` 匹配不到 `Explore`，省略、`""`、`"*"` 和 `.*` 会命中。

`TeammateIdle` 只做一行对照：不支持 matcher，闲下来不是这只收工事件。不重放 11 月 18 日的套件。

```bash
python3 demos/subagentstart-stop/run_demo.py
```

通过时最后一行是 `result=pass`。
