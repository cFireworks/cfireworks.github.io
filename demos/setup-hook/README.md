# Setup 与 SessionStart 的开火契约

本地脚本。按 2026-11-27 08:35（Asia/Shanghai）打开的 [Hooks reference](https://code.claude.com/docs/en/hooks) 里 `Setup` 一节、matcher 规则、退出码表、Decision control 总表、「Events that fire before MCP servers are available」，[CLI reference](https://code.claude.com/docs/en/cli-reference) 的 `--init`、`--init-only`、`--maintenance`、`--debug-file`、`--include-hook-events`，[headless](https://code.claude.com/docs/en/headless) 的 Read session metadata，以及 [plugins/components](https://code.claude.com/docs/en/plugins/components) 里挂在 `SessionStart` 上的安装命令，在本地走一遍。

不调用 API，不访问网络，不启动 Claude Code，不执行 `npm install`，不读密钥，不依赖本机有没有 `jq`。

这不是 settings 里的 hook，也不是 Claude Code 运行时。夹具按这些页上的契约模拟，`runtime_version_probe=0`。`Setup` 写在 changelog 的 **2.1.10**（2026-01-17）。写作时 GitHub 最新正式版仍是 **v2.1.332**。版本不做成运行时分支。

```bash
python3 demos/setup-hook/run_demo.py
```

stdout 最后一行是 `result=pass`。上一行是 `network=0 npm_invoked=0 claude_invoked=0 runtime_version_probe=0`。

## 夹具在断言什么

stdin 形状沿用参考页的示例：`hook_event_name` 为 `Setup`，`trigger` 为 `init` 或 `maintenance`，并带 `session_id`、`transcript_path`、`cwd`。`trigger` 写成 `startup` 时不算一份 Setup 输入。

matcher 只走精确名单。`init` 打在 `--init-only` 和 `claude -p --init` 上。`maintenance` 打在 `claude -p --maintenance` 上。`init|maintenance` 两边都打。含正则特殊字符的 matcher 不模拟。

`claude --init-only`：`Setup`（`trigger=init`）和 matcher 为 `startup` 的 `SessionStart` 都会跑，然后 `conversation=0`。成功（退出码 0、没有 stdout/stderr）时 `terminal` 是空字符串。模拟日志里有 `event=Setup` 和 `event=SessionStart`。不调用 `--debug-file`，也不假定日志整行原文。退出码不是成功时，终端会不会多印一行，页上没写，`terminal_exact=0`。

日常 `claude`、resume、`/clear`、compaction、fork，以及不带 `--init` / `--maintenance` 的 `claude -p`：`setup_command_calls=0`。只有对应 matcher 的 `SessionStart`。

任何退出码都 `continued=1`、`blocked=0`。`systemMessage`、`continue`、顶层 `decision`、顶层 `additionalContext`、`hookSpecificOutput.additionalContext` 记进 `discarded`，`injected_context=0`。退出码表写 Setup 的 exit 2 是 Exit code and stderr are ignored，所以 `user_notice=0`。这和 `SessionStart` 的 Shows stderr to user only 不是同一句。

`-p` 的普通文本输出不包含钩子的 stdout/stderr。`hook_response=1` 只在 `--output-format stream-json --verbose` 时出现，里面带上原始 stdout、stderr 和退出码。`--include-hook-events` 不作为出现的条件，`include_flag_required=0`。`hook_response` 的其余字段以 SDK 类型页为准，这两页没有完整字段表，夹具不编。

`Setup` 上只有 `type: "command"` 会跑。`http`、`prompt`、`agent` 记进 `setup_type_skipped`，不发明各自的调试原文。`mcp_tool` 调用次数是 0，调试串是 `mcp_tool hooks are not available for the 'Setup' hook event (no MCP client context)`。`SessionStart` 在启动时（含 resume）用同一句、事件名换成 `SessionStart`。`/clear` 和 compaction 之后，`session_mcp_calls=1`。fork 时 `mcp_tool` 跑不跑，页上没单独写，`fork_mcp_simulated=0`。

`CLAUDE_ENV_FILE`：Bash 的 `Setup` 在 `-p --init` 进入会话后，`subsequent_bash=1`，后续命令看得到变量。`--init-only` 不开启对话，`subsequent_bash=0`。PowerShell 钩子没有这个变量，`env_file=0`。不模拟下一次 `CwdChanged` 的清除。

插件：只挂 `Setup` 的 init 安装，日常 `claude` 和 resume 的 `would_install=0`。`SessionStart` 按「没有 `node_modules` 再装」和「两份 `package.json` 不一致再装」两条分别记 `would_install`。`npm_invoked` 始终是 0。

`-p` 没给 prompt 时 `needs_prompt=1`，报错原文不编，`prompt_error_exact=0`。`--init-only` 不要求 prompt，也不要求 `-p`。

## 官方示例，不要在这里执行

plugins/components 把可运行的安装示例挂在 `SessionStart` 上，不是 `Setup`。下面这段只作对照。夹具不调用它。

```bash
diff -q "${CLAUDE_PLUGIN_ROOT}/package.json" "${CLAUDE_PLUGIN_DATA}/package.json" >/dev/null 2>&1 || (cd "${CLAUDE_PLUGIN_DATA}" && cp "${CLAUDE_PLUGIN_ROOT}/package.json" . && npm install) || rm -f "${CLAUDE_PLUGIN_DATA}/package.json"
```
