# MessageDisplay 的显示契约

本地脚本。按 2026-11-23 08:26（Asia/Shanghai）打开的 Hooks reference 里 `MessageDisplay` 专项、matcher 表、退出码表、Decision control，以及 hooks-guide 的生命周期表、无 matcher 行和默认超时，在本地走一遍。

不调用 API，不读真实密钥，不访问网络，不启动 Claude Code，不依赖本机有没有 `jq`，也不睡眠。假密钥只有 `sk-example-not-a-real-key` 和 `AKIA_EXAMPLE_NOT_REAL`。

这不是 settings 里的 hook，也不是 Claude Code 运行时。

交互模式按夹具自己的切法分成多批。同一 `message_id` 下 `index` 递增，恰好一批 `final: true`。以换行结束的消息，最后一批 `delta` 为空。结束信号是 `final`。空 `delta` 追加进去，不会把已经拼好的屏幕文本清掉。不以换行结束时，最后一批可以停在行中间，`delta` 非空，结束仍看 `final`。

`displayContent` 拼起来是屏幕。各批原始 `delta` 拼起来是 transcript / 模型视图。去掉 markdown，或把假密钥换成 `***`，两边分叉：屏幕是替换后的，记录仍是原文。省略 `displayContent` 时屏幕等于原文。没有 markdown 的批次，替换前后是同一段字。

非交互（Agent SDK、`claude -p`）只有一次调用：`index` 为 0，`final` 为 true，`delta` 为全文。收集到的 `delta` 总文本和多批次模式相同。

exit 2 时屏幕是原文，`blocked=0`。JSON 里的 `continue: false` 和 `systemMessage` 丢掉。成功路径仍按 `displayContent` 换屏幕。失败（脚本没有打出 JSON，对应页上「缺 `jq`」那种）屏幕回到该批原文，失败记在 `debug`，`session_notes_failure=0`。超时同样回落到该批原文。夹具用 `timed_out` 标记，`slept=0`，不真等 10 秒。只超时其中一批时，其余批仍用替换文本。

配了 matcher 也按「不支持 matcher」处理，`silently_ignored=1`，凡是有文本的助手消息都开火。无文本的纯工具回复不开火。工具结果和用户键入的文字不进钩子输入，渲染保持原文。

`message_id` 各批稳定，并且 `correlates_transcript_msg_id=0`。页上写它不是 API 的 `msg_…` id，不能拿去对 transcript。夹具只标注这句，没有打开一份真实 transcript。

`if` 写在 `MessageDisplay` 上时钩子不跑。这句来自 handler 字段：`if` 只在工具事件上评估。

默认超时记成 10 秒。`command` / `http` / `mcp_tool` 的一般默认是 600，`UserPromptSubmit` 是 30。用途列表记成今天打开的两条，`lists_redact_keys=0`。改写内容的名单里没有 `MessageDisplay`。

多只钩子的 `displayContent` 留下谁的、`prompt` / `agent` 是跳过还是报错、`displayContent` 空字符串算不算省略、超时记在哪里、一条消息两批 `final` 怎么结算，这些格子是 `not_stated`，`simulated=0`。

官方示例用 `jq` 去掉 `**` 和行内反引号。夹具用同样顺序的 Python 替换，测试不调用 `jq`。对照用的脚本是：

```bash
#!/bin/bash
jq '{hookSpecificOutput: {hookEventName: "MessageDisplay", displayContent: (.delta | gsub("\\*\\*"; "") | gsub("`"; ""))}}'
```

```bash
python3 demos/messagedisplay/run_demo.py
```

通过时 stdout 最后一行是 `result=pass`。
