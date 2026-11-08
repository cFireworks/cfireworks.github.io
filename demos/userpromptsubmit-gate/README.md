# 入口闸挂在哪一只事件上

本地脚本。先走一次 `SessionStart`，再走一次带 `prompt` 字段的 `UserPromptSubmit`。原文提示不变。处理器是 `session_start_exit2`、`user_prompt_exit2`、`user_prompt_block_json`、`inject_nested`、`inject_toplevel`、`none`。

`session_start_exit2` 的 `prompt` 是 `reaches_model`，`notice` 是 `user_only`。`user_prompt_exit2` 和 `user_prompt_block_json` 的 `prompt` 是 `blocked`。`inject_nested` 的 `injection` 是 1，原话仍是 `unchanged`。`inject_toplevel` 的 `injection` 是 0，提示仍进模型。`none` 不是拦截。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks) 的退出码表，和 [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide) 的 `additionalContext` 嵌套例子。

```bash
python3 demos/userpromptsubmit-gate/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `session_start_exit2` | exit 2 挂在会话开头 |
| `user_prompt_exit2` | exit 2 挂在这一轮提示上 |
| `user_prompt_block_json` | exit 0，顶层 `decision: "block"` |
| `inject_nested` | `additionalContext` 在 `hookSpecificOutput` 里 |
| `inject_toplevel` | 同名字段写在 JSON 顶层 |
| `none` | 什么都不交 |
