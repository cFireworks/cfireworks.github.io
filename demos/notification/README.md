# Notification 的提醒契约

本地脚本。按 2026-11-24 08:32（Asia/Shanghai）打开的 Hooks reference 里 `Notification` 专项、matcher 表、退出码表、Decision control 总表、Emit terminal notifications，以及 `PermissionRequest` 里「大约六秒才跑 `permission_prompt`」那句，在本地走一遍。

不调用 API，不访问网络，不启动 Claude Code，不弹系统通知，不写 `/dev/tty`，不依赖本机有没有 `jq`，也不睡眠。六秒和六十秒是虚拟时钟上的加法。

这不是 settings 里的 hook，也不是 Claude Code 运行时。

stdin 的形状对齐官方示例：`hook_event_name` 为 `Notification`，带 `message` 和 `notification_type`。`title` 可选，示例本身没有，夹具另有一条带上它。

空 matcher、`"*"`、省略，对 matcher 表里的 14 种类型都开火。`permission_prompt` 只打这一种，不打 `idle_prompt` 或 `auth_success`。`permission_prompt|idle_prompt` 打这两种，不打 `auth_success`。

没有 decision control。exit 2 和 stderr 被忽略，通知仍视为已发送、未被修改。JSON 里的 `continue: false` 和 `systemMessage` 丢掉。`terminalSequence` 在这之后仍记为「由宿主发出」，包括 exit 2 那一次。钩子带 `async: true` 或 `asyncRewake: true` 时，该字段忽略。`-p`、Agent SDK、界面没开着，也同样忽略。CSI 和 OSC 52 在允许名单外，整个字段忽略。OSC 777、OSC 0、OSC `9;4` 和裸 BEL 保留。

`preferredNotifChannel: "notifications_disabled"` 时钩子仍然跑。页上没有在这一节列出该设置的其他取值，夹具不模拟那些取值。

终端会话：权限窗在 `t=0` 出现。`PermissionRequest` 在这一刻开火，不等六秒。`permission_prompt` 在大约六秒且期间无按键时开火。按键把到期时刻推到这次按键加六秒。权限窗出现之前的按键不参加。沙箱命令的网络请求不走 `PermissionRequest`；终端里的 `permission_prompt` 要 v2.1.246 或更晚，到点才开火。另一只对话框还开着时，六秒仍从请求到达起算，到点的通知记为 `notification_while_queued=1`。

交给 `canUseTool` 的会话（Claude Desktop、VS Code 扩展）：六秒不因打字推迟。用户或 `PermissionRequest` 在到期前作答，则不跑 `permission_prompt`。到期之后才作答，通知已经算开火。`CLAUDE_CODE_DISABLE_PERMISSION_PROMPT_NOTIFY_HOOKS=1` 在这类会话里关掉 `permission_prompt`。v2.1.233 之前不开火。

`idle_prompt`：回复在 `t=0` 结束，无按键、无仍在跑的 background agent，大约 60 秒时开火。期间打过字，到 `t=120` 仍不发。后台 agent 还在跑则不发；已经停了，到点可以发。等待用量限制重置期间不发。等待自行结束时记 `quota_family=1`，不挑 `quota_auto_resume_*` 里的哪一条。

`auth_storage_failure` 代替 `auth_success`，两条不同时出现。

`if` 写在 `Notification` 上时钩子不跑。`PermissionRequest` 在工具事件名单里，`if` 会求值。夹具只标注这句，不模拟 Bash 规则匹配。

终端里「人先答了就取消 `permission_prompt`」、`preferredNotifChannel` 的其他取值、上述环境变量在终端会话里是否生效、`prompt` / `agent` 是跳过还是报错、elicitation 的按键是否逐次推迟、quota 三条里具体哪一条，这些格子是 `not_stated` 或 `not_picked`，`simulated=0`。

官方示例用 `jq` 把 OSC 777 放进 `terminalSequence`。夹具用同样的序列形状，测试不调用 `jq`。对照用的脚本是：

```bash
#!/bin/bash
input=$(cat)
title="Claude Code"
body=$(jq -r '.message // "Needs your attention"' <<<"$input")
seq=$(printf '\033]777;notify;%s;%s\007' "$title" "$body")
jq -nc --arg seq "$seq" '{terminalSequence: $seq}'
```

```bash
python3 demos/notification/run_demo.py
```

通过时 stdout 最后一行是 `result=pass`。
