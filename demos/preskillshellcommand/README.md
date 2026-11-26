# PreSkillShellCommand 的拦截契约

本地脚本。按 2026-11-26 08:27（Asia/Shanghai）打开的 Hooks reference 里 `PreSkillShellCommand` 一节、matcher 规则、`if` 的 Bash 表、退出码表、Decision control 总表，以及 skills.md 的 Inject dynamic context，在本地走一遍。

不调用 API，不访问网络，不启动 Claude Code，不执行注入命令，不依赖本机有没有 `jq`。`echo 'rm -rf'` 和 `echo $(rm -rf /)` 只作为输入字符串。

这不是 settings 里的 hook，也不是 Claude Code 运行时。夹具按 v2.1.332 的契约模拟，`runtime_version_probe=0`。2.1.331 及更早会在 settings 里写了这个事件名时弹出 `Unknown hook event "PreSkillShellCommand" was ignored`，并且不调用这只钩子就跑注入命令。那一条不做成运行时分支。

stdin JSON 含 `hook_event_name: "PreSkillShellCommand"`、`tool_name`（`Bash` 或 `PowerShell`）、`tool_input.command`、`tool_use_id`、`command_name`、`command_source`、`invoked_by`、`permission_mode`。`tool_use_id` 不写入 transcript，也不对应一次工具调用。

matcher 省略、`""`、`"*"` 打到每个工具名。只含字母、数字、`_`、`-`、空格、`,`、`|` 时做精确列表，所以 `Bash|PowerShell` 和 `Bash, PowerShell` 都打这两种工具。其余按未锚定正则。夹具只用 Python `re`，测过的正则是 `^Bash$`，和 JavaScript 的整串匹配同结果。没有把其余正则差异当成已核实。

`if` 在这只事件上会求值。不匹配则钩子不跑。Bash 只覆盖参考页「How `if` patterns match Bash commands」那五行：

- `Bash(git *)` 对 `FOO=bar git push`：剥掉前导赋值后钩子跑
- `Bash(git *)` 对 `npm test && git push`：`&&` 两侧都看
- `Bash(rm *)` 对 `echo $(rm -rf /)`：`$()` 里的命令会让钩子跑。夹具随后 deny，`executed=0`，不把这串交给 shell
- `Bash(rm *)` 对 `echo $(date)`：钩子不跑
- `Bash(git push *)` 对 `echo $(date)`：模式比命令名更长，又遇到 `$()`，钩子照跑

页上写拆不开就让钩子跑。夹具只把「单引号不成对」当成拆不开，不是完整的 bash 分词器。`PowerShell(...)` 没有这张表，`powershell_if_not_stated` 的 `simulated=0`。

Exit 0 且无 decision，或 `permissionDecision: "allow"`：`contract_runs=1`，除非另一只钩子拦住。Exit 2、`permissionDecision: "deny"`、顶层 `decision: "block"`：命令不跑，`skill_loaded=1`，占位符是 `[not run: blocked by hook: <reason>]`。你键入技能名时，终端行是 `Not run in /<name>: <command> (blocked by hook: <reason>)`。

`ask`、`defer`、任何 `updatedInput`：按 deny 拦住。`asked=0`，`deferred=0`，`rewritten=0`。不断言会询问，也不断言会改参数。

`continue: false`：整次调用失败，`Operation stopped by hook: <stopReason>`。Claude Code 在跑第一条之前收齐答复，所以还没轮到的命令也不跑。exit 2 同时带 `continue: false` 时谁先算，页上没有对这只事件写成一句，`simulated=0`。

exit 1 且没有 JSON，或超时，又没设 `onFailure: "block"`：`contract_runs=1`，终端前缀是 `Ran anyway in /<name>`。设了 `onFailure: "block"` 则不跑。exit 1 但打印了通过校验的 deny JSON 时，退出码被忽略，字段自己做决定。Windows 没有 Git Bash、shell 形式、`onFailure` 没设时，失败改成拦截。Code Mode 里已经跑过代码时，超时默认拦截。这两条例外都在夹具里。

同一脚本挂在 `PreToolUse` 和 `PreSkillShellCommand` 上时，`hookEventName` 留成 `PreToolUse` 仍然能拦住注入命令。脚本只挂在 `PreToolUse` 上时，注入命令的 `hook_calls=0`。auto mode 里本应询问的命令加载时不跑，`later_event=PreToolUse`。只挂在 `PreSkillShellCommand` 上的脚本看不见那次后续工具调用。

权限检查在钩子之前。deny 规则 abort 整次调用，错误是 `Shell command permission check failed for pattern "..."`，钩子次数是 0。非 auto mode 下检查结果不是 allow，也会 abort。页上没有给这第二种单独的报错原文，`permission_error_exact=0`。钩子拦住单条时技能仍加载。命令自身失败会 abort 整次调用，报 `Shell command failed for pattern "..."`。那个退出码是夹具输入，不是子进程。搜索命令 exit 1 的豁免不模拟。

`disableSkillShellExecution` 对受影响来源把命令换成 `[shell command execution disabled by policy]`，钩子次数是 0。bundled 和 managed 不受影响。夹具用 `policy_affects_source` 表示这条来源在不在 user、project、plugin、additional-directory 里，不把某个 `command_source` 猜成 bundled 或 managed。

MCP 技能的 `!` 命令不会跑，`not_this_gate=1`。夹具不把它们写成这只钩子的输入。

技能自己的 frontmatter：第一次加载、子代理内部、fork，都打不到自己的注入命令。父会话第二次加载打不打得到，以及子代理定义在非 fork 时打不打得到，`simulated=0`。settings 和 plugin 在第一次加载和 fork 里都会打到。

`prompt` 和 `agent` 在这只事件上跑不了，并拦住 matcher 对上的命令。async 的 `permissionDecision` 和 `continue` 拦不住。`http` 和 `mcp_tool` 只复用同一份 JSON，`network=0`，不发请求。

Remote Control 已连接时仍拦，用户和 Claude 都看不到原因，`debug_log=1`。这种连接下占位符怎么拼，页上没写，夹具不填那串字。

`hookEventName` 既不是 `PreToolUse` 也不是 `PreSkillShellCommand` 时，认不认这份 JSON，页上没写成一句，`simulated=0`。缺了 `hookEventName` 按 schema 无效：exit 0 走 `Ran anyway`，exit 2 仍用 stderr 拦。

官方示例用 `jq`。夹具用同样的字段形状，测试不调用 `jq`。对照用的脚本是：

```bash
#!/bin/bash
# .claude/hooks/block-rm.sh
COMMAND=$(jq -r '.tool_input.command')

if echo "$COMMAND" | grep -q 'rm -rf'; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: "Destructive command blocked by hook"
    }
  }'
else
  exit 0
fi
```

手册写的确认方式是建 `.claude/skills/hook-test/SKILL.md`，正文一行 `` !`echo 'rm -rf'` ``，再在终端输入 `/hook-test`。夹具不跑这条命令。`contract_runs=1` 只表示参考页写这条命令会跑，本脚本的 `executed` 仍是 0。

```bash
python3 demos/preskillshellcommand/run_demo.py
```

通过时 stdout 最后一行是 `result=pass`。
