# CwdChanged 与 FileChanged 的环境契约

本地脚本。按 2026-11-22 08:32（Asia/Shanghai）打开的 Hooks reference 专项、退出码表、Decision control、类型名单、`CLAUDE_ENV_FILE` 那一节，以及 hooks-guide 里「Reload environment when directory or files change」，在本地走一遍。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不跑 direnv、nix 或 devbox。不 `cd` 进用户目录，不改这个脚本以外的 shell 环境。Bash 预执行是子进程 `source` 夹具自己的临时文件。监视和改写的文件都在临时目录里，脚本结束就删。

这不是 settings 里的 hook，也不是 Claude Code 运行时。

`CwdChanged` 的输入带 `old_cwd` 和 `new_cwd`。官方示例里 `cwd` 与 `new_cwd` 相同。exit 2、`decision: "block"`、`continue: false` 都不把目录换回去。`continue` 丢掉。`systemMessage` 和 `watchPaths` 被读到。`systemMessage` 在交互会话里是短暂终端通知，不进 SDK 消息流。配了 matcher 也按「不支持 matcher」处理，每次换目录都开火。

下一次 `CwdChanged` 开始时，夹具先把 `CLAUDE_ENV_FILE` 截空，再让钩子写。这是把「下一次 CwdChanged 清掉旧变量」和「这一次钩子写进去的要进后续 Bash」接起来的读法。页上没有给出清文件的命令。

持久化那一节建议用 `>>`，把别的钩子写过的变量留住。指南的 direnv 示例用 `>`。两格分开跑，不收成一条规则。不跑 direnv。钩子并行时 `>` 会不会互盖，`parallel_simulated=0`。

`FileChanged` 建名单按 `|` 切开、按字面文件名注册。`^\.env` 是名叫 `^\.env` 的文件。matcher `"*"` 加进名单的是名叫 `*` 的文件。省略 matcher 的那一组匹配所有已监视文件，不往名单里加名字。带 `.` 或 `-` 的 matcher，过滤走正则路径；夹具不推演它匹配哪些 basename，`pair_filter_outcome=not_deduced`。`change` / `add` / `unlink` 走「`watchPaths` 播种 + 省略 matcher」这条页上写明的路。

`watchPaths` 替换动态名单。matcher 配上的路径始终留着。空数组清掉动态名单。什么都没点名时监视器不开始。SessionStart 播下的路径，夹具放进同一份动态名单，随后的空数组会清掉它。页上没有第三句说「SessionStart 的路径另算一份」。`session_seed_join=seed_is_dynamic` 标的是这个衔接。

无条件改写被监视文件会再触发一次。夹具数到第二次就停，`infinite=0`。

`DirectoryAdded` 只做边界。`--add-dir` 启动、`/permissions` 的 Workspace 页、已经是工作目录或在其内部，不开火。`/add-dir` 和 `register_repo_root` 开火，添加已经完成，拦不住。exit 2 的 stderr 进调试日志，和 `CwdChanged` 那一行「Shows stderr to user only」不是同一格。

`$'...'` 和未转义的 `$PATH` 按专项标成「PowerShell 拿不到这些变量，Bash 拿得到」。没有执行 PowerShell，没有发明解析器。以 `"shell": "powershell"` 跑的钩子，以及没有 Git Bash 时 Windows 上默认跑 PowerShell 的钩子，夹具里没有 `CLAUDE_ENV_FILE`。

`EnterWorktree` 会不会让 `CwdChanged` 开火、子代理里的 `cd`、`watchPaths` 在 JSON 的哪一层、配了 `prompt` 或 `agent` 是跳过还是报错，这几格 `simulated=0`。

```bash
python3 demos/cwdchanged-filechanged/run_demo.py
```

通过时 stdout 最后一行是 `result=pass`。
