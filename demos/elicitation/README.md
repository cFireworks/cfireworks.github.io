# Elicitation 与 ElicitationResult 的回传契约

本地脚本。按 2026-11-25 08:27（Asia/Shanghai）打开的 Hooks reference 里 `Elicitation`、`ElicitationResult` 两节、matcher 表、退出码表、Decision control 总表，以及「`hookSpecificOutput` 只在 exit 0 生效」那一条，在本地走一遍。

不调用 API，不访问网络，不启动 Claude Code，不弹出 MCP 对话框，不打开浏览器，不依赖本机有没有 `jq`，也不睡眠。大约六秒只记成一个数。

这不是 settings 里的 hook，也不是 Claude Code 运行时。

`Elicitation` 的 stdin 对齐官方示例：`hook_event_name` 为 `Elicitation`，带 `mcp_server_name`、`message`。form 模式带 `mode` 和 `requested_schema`。url 模式带 `mode` 和 `url`。`elicitation_id` 可选。

`ElicitationResult` 的 stdin：`hook_event_name` 为 `ElicitationResult`，带 `mcp_server_name`、`action`，以及可选的 `content`、`mode`。

matcher 对 MCP 服务器名。省略、`""`、`"*"` 打到每台服务器。`issue-tracker` 不处理 `other-server`。`issue-tracker|docs` 与 `issue-tracker, docs` 打这两台，不打 `other`。

`Elicitation` 在 exit 0 打印带 `action` 的 `hookSpecificOutput` 时，对话框不出现，`ElicitationResult` 的调用次数是 0，服务器收到这份结果。`accept` 的 `content` 交给服务器。url 模式的 `accept` 记 `url_opened=0`。无输出且 exit 0，记 `dialog=1`、`server_action=pending`。

exit 2 把请求记成 `decline`，对话框不出现，同一只钩子的 `hookSpecificOutput` 不生效。`reason`、`systemMessage`、`continue`、stderr 都记为没被看见。顶层 `"decision": "block"` 覆盖同一份输出里的 `action`，结果同样是 `decline`。夹具按今天的页模拟。v2.1.105 到 v2.1.284 的修复之前，顶层 `decision` 曾被忽略；夹具不按版本分支，`pre_fix_ignore_simulated=0`。

多只钩子里只要有一只 `decline`，就盖过另一只的 `accept` 或 `cancel`。`accept` 和 `cancel` 同时出现、又没有 `decline` 时，谁赢页上没写，`simulated=0`。

`ElicitationResult`：无输出则用户的 `action` 和 `content` 原样回传。`accept` 的 `content` 整份替换，漏掉的字段不保留。没有 `action` 的 `hookSpecificOutput` 被忽略。`decline` 拦住，用户填的值不送出。`cancel` 把 action 记成 `cancel`；要扣住值，页上写的是改回 `decline`，`cancel` 扣不扣不猜。

用户的 `action` 已是 `decline` 或 `cancel` 时，Result 仍跑。不看输入 `action` 就返回 `accept`，会把拒绝翻成接受。先检查再改 `username` 的那条，输入不是 `accept` 时不打印，原来的拒绝留着。脚本里把没改的字段抄进新对象；宿主不做合并。

`if` 写在这两只事件上时钩子不跑。

旁边两条 `Notification`：`elicitation_dialog` 和 `elicitation_url_dialog` 即使 exit 2，并带上 `decision: "block"`，也不把请求记成 decline，也不跳过对话框。`slept=0`。

官方示例用 `jq`。夹具用同样的字段形状，测试不调用 `jq`。对照用的脚本是：

```bash
#!/bin/bash
input=$(cat)
fields=$(jq -c '.requested_schema.properties // {} | keys' <<<"$input")

if [ "$fields" = '["project_key"]' ]; then
  jq -n '{hookSpecificOutput: {hookEventName: "Elicitation", action: "accept", content: {project_key: "DOCS"}}}'
fi
```

```bash
#!/bin/bash
input=$(cat)

if [ "$(jq -r '.action' <<<"$input")" = "accept" ]; then
  jq '{hookSpecificOutput: {hookEventName: "ElicitationResult", action: "accept", content: (.content + {username: (.content.username + "@example.com")})}}' <<<"$input"
fi
```

url 模式直接拒绝、表单留给对话框的对照是：

```bash
#!/bin/bash
if [ "$(jq -r '.mode')" = "url" ]; then
  exit 2
fi
```

手册写确认方式是 `claude --debug`，debug log 含 `Elicitation resolved by hook:` 和 `accept`。夹具不跑这条命令。

```bash
python3 demos/elicitation/run_demo.py
```

通过时 stdout 最后一行是 `result=pass`。
