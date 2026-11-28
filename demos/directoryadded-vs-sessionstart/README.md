# DirectoryAdded 与 SessionStart 的加目录契约

本地脚本。按 2026-11-28 08:32（Asia/Shanghai）打开的 [Hooks reference](https://code.claude.com/docs/en/hooks) 里 `DirectoryAdded` 专节、matcher 表、退出码表、Decision control 总表、Persist environment variables 的 NOTE、`timeout` 默认值，[CLI reference](https://code.claude.com/docs/en/cli-reference) 的 `--add-dir`，以及 [permissions](https://code.claude.com/docs/en/permissions) 的 Working directories 与「Additional directories grant file access, not configuration」，在本地走一遍。

不调用 API，不访问网络，不启动 Claude Code，不读密钥，不装依赖，不把脚本写进 settings。

这是按官方页做的本地模拟，不是 Claude Code 运行时。`runtime_version_probe=0`。`DirectoryAdded` 写在 changelog 的 **2.1.219**（2026-07-24）。写作时 GitHub 最新正式版仍是 **v2.1.332**。版本不做成运行时分支。

```bash
python3 demos/directoryadded-vs-sessionstart/run_demo.py
```

stdout 最后一行是 `result=pass`。上一行是 `network=0 claude_invoked=0 runtime_version_probe=0`。

## 夹具在断言什么

启动 `--add-dir`：路径先进入工作目录集合，`SessionStart` 开火，`DirectoryAdded` 不开火。`covers_sentence=1` 只标在这面旗标上。

TypeScript `additionalDirectories` 和 Python `add_dirs` 记成 `--add-dir`。`register_repo_root=0`。它们不走中途那只钩。

settings 里的 `additionalDirectories`：`directory_added=0`。它不在开火句里（`in_fire_sentence=0`），也不在三条 doesn't fire 名单里（`in_does_not_fire_list=0`）。`covers_sentence=0`。`file_access_only=1`，`config_exceptions=0`。

`/permissions` 的 Workspace 页、已经是工作目录、位于某个工作目录内部：`directory_added=0`。主目录的子路径另记权限页那句「不新增工作目录」，`working_directory_added=0`，`permissions_requires=2.1.257`，`runtime_tested=0`。附加目录内部只按钩子页记不开火，`permissions_sentence=0`，`working_directory_added=not_read`。

中途 `/add-dir`：`source=slash_command`，`blocked=0`，`added_before_hook=1`，`background=1`，`timeout_default=600`。`async_true_equated=0`。页上没有把这只事件写成 `"async": true`，夹具不套用「后台跑了就不再强制 timeout」。

`register_repo_root`：开火。`systemMessage` 和 exit 2 的 stderr 都进 `debug_log`。`next_turn=0`，`user_notice=0`。失败计数那句写在 `slash_command` 下面，这条 `transcript_failed=0`。

`slash_command` 的 `systemMessage` 记为下一轮交给 Claude 的上下文，`user_notice=0`，不进 `debug_log`。exit 2 的 stderr 进 `debug_log`，目录仍在集合里。`continue` 在 `discarded` 里。JSON 里的 `decision` 不改变 `blocked`。

`DirectoryAdded` 的环境里没有 `CLAUDE_ENV_FILE`。脚本可以往猜测路径写 `export`，后续 Bash 不 source 那份文件，`bash_sees=empty`。`SessionStart` 会 source 资格名单里的那份，`bash_sees=from-start`。猜测路径两边都不读。

matcher `slash_command` 滤得掉 `register_repo_root`，反过来也一样。事件仍然发生，目录已经加上，这一组 `hook_ran=0`。

信任对话框、网络路径校验、`"async": true` 与这只事件是否同一件事，夹具不模拟。
