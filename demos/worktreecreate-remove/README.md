# WorktreeCreate 与 WorktreeRemove 的路径 / 退出码契约

本地脚本。按 Hooks reference 的 `WorktreeCreate` / `WorktreeRemove` 专项、退出码表、Decision control、类型名单，以及 worktrees 页里和这两只钩子直接相关的句子，在本地走一遍。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不执行 `git worktree` 或 `svn checkout`。删除只发生在脚本自己建的临时目录里。夹具不是 settings 里的 hook。

command hook 的 stdout 最后一行非空（先剥 ANSI）当作路径。打出 JSON 也按路径读，不按 `decision` 读。HTTP hook 读 `hookSpecificOutput.worktreePath`。`continue` 和 `systemMessage` 丢掉。

`WorktreeRemove` 只对钩子建出来的路径开火。exit 0 算已移除，即使目录还在。这一格是页上写明的风险：钩子必须自己把目录删掉。夹具里 `remove_exit0_dir_remains` 的 `trap=1`、`dir_exists=1`、`counts_as_removed=1` 就是它。非零退出只有目录还在才算失败，没有 git 回退。JSON 丢掉。

子代理或 workflow 代理收工不跑 Remove。没配 Remove 时，退出会话或 `ExitWorktree` 按 `git worktree remove --force` 模拟：git 认得出的删掉，认不出的留下。`claude remote-control` 清理留下，消息前缀是 `worktree removal failed, kept:`。

`prompt` / `agent` 配上之后是跳过还是报错，专项没有写。`mcp_tool` 在支持名单里，路径怎么交回，输出那一节没有写。这两格 `simulated=0`。

指南的 no-matcher 行包含 `CwdChanged`。参考页把 `CwdChanged` 单独成行。夹具记下分行，不收成第三张表。

```bash
python3 demos/worktreecreate-remove/run_demo.py
```

通过时最后一行是 `result=pass`。
