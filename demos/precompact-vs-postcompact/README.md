# 上下文平面闸挂在哪一只事件上

本地脚本。假一次 `manual` 压缩，一次限额前的 `auto`，一次「限额错误恢复」的 `auto`。处理器是 `pre_exit2`、`pre_block_decision`、`pre_stdout_instructions`、`post_only`、`sessionstart_compact`、`none`。

`kind` 是夹具里的名字，不是参考页上的输入字段。`manual` / `auto` 才是 `trigger`。限额前和限额错误恢复，参考页没有另给字段。`auto` 的 `custom_instructions` 恒为 `null`。

`pre_exit2` 和 `pre_block_decision` 在 `manual` 和限额前的 `auto` 上把 `compacted` 记成 0，`continued` 记成 1，`request_failed` 记成 0。同一对处理器挂在限额错误恢复的 `auto` 上，`compacted` 是 0，`request_failed` 是 1。这是对官方那两句后果的模拟。

`pre_stdout_instructions` 放行。短 stdout 整段进摘要指令。超过 10,000 字符则截到上限，再追加夹具标记 `[fixture truncated]`。参考页只写会追加一个标记，没有给出标记原文。这个标记不冒充官方文本。`TAIL` 落在截断点之后，不会留在指令里。

`post_only` 在压缩之后跑。JSON 里写了 `additionalContext`。`compacted` 是 1，`saw_summary` 是 1，`model_context_reinjected` 是 0。`sessionstart_compact` 走纯文本 stdout，`model_context_reinjected` 是 1。`none` 压缩发生，没有指令，也没有补种。

`pre_discarded_fields` 只有 `continue: false` 和 `systemMessage`，没有 `decision`。`compacted` 是 1。`auto_before_limit_if_skipped` 给 PreCompact 写了 `if`，hook 不开火，压缩照常发生。`manual_post_if_skipped` 给 PostCompact 写了 `if`，同样不开火。`manual_narrow_exit2` 的 matcher 是 `manual`，exit 2 拦住。`auto_before_limit_wrong_matcher` 用同一条 matcher，来的是限额前的 auto，hook 不开火。

空 matcher 在输出里写成 `matcher=empty`。夹具把它当成对上每一次。非空只按 `|` 切。不模拟逗号，也不模拟正则。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks#precompact) 的 PreCompact、PostCompact 小节，和 [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide) 里压缩后补种那一节。

```bash
python3 demos/precompact-vs-postcompact/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `manual_pre_exit2` | 手动压缩，exit 2，请求不失败 |
| `manual_pre_block_decision` | 手动压缩，顶层 `decision: "block"` |
| `auto_before_limit_pre_exit2` | 限额前 auto，exit 2，未压缩继续 |
| `auto_before_limit_pre_block_decision` | 限额前 auto，顶层 `decision: "block"` |
| `auto_limit_error_pre_exit2` | 限额错误恢复，exit 2，当前请求失败 |
| `auto_limit_error_pre_block_decision` | 限额错误恢复，顶层 `decision: "block"`，当前请求失败 |
| `*_pre_stdout_instructions` | 放行，短 stdout 进入摘要指令 |
| `manual_stdout_over_cap` | stdout 超过 10,000 字符，截断并加夹具标记 |
| `*_post_only` | 压缩后跑，`additionalContext` 补不回模型 |
| `*_sessionstart_compact` | `SessionStart` 的 `compact`，纯文本 stdout 补回 |
| `*_none` | 什么都不交 |
| `manual_pre_discarded_fields` | 没有 `decision`。`continue` 和 `systemMessage` 不拦 |
| `auto_before_limit_if_skipped` | PreCompact 上写了 `if`，hook 不开火 |
| `manual_post_if_skipped` | PostCompact 上写了 `if`，hook 不开火 |
| `manual_narrow_exit2` | matcher 是 `manual`，对上手动压缩 |
| `auto_before_limit_wrong_matcher` | 同一条 matcher，来的是 auto |
