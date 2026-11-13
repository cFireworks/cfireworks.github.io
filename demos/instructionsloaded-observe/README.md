# 规则加载这只事件是摄像头

本地脚本。假一次会话开头的急加载（`load_reason` 为 `session_start`），一次嵌套 `CLAUDE.md`（`nested_traversal`），一次带 `paths` 的条件规则（`path_glob_match`），一次 `CLAUDE.md` import `AGENTS.md`（`include`），一次压缩之后的指令重载（`compact`），一次 `CLAUDE.md` 指向 `AGENTS.md` 的 symlink（按普通 `CLAUDE.md` 急加载），一次经 Project instructions 设置直接读取的 `AGENTS.md`（事件不开火）。

处理器是 `il_exit2`、`il_block_decision`、`il_additional_context`、`il_discarded`、`il_audit_log`、`il_with_if`、`il_env_write`、`sessionstart_compact_stdout`、`none`。一次只挂一只。

根上 `CLAUDE.md` 的路径和 `memory_type: "Project"` 照着 Hooks reference 的例子。`globs` 的字符串照记忆页 `paths` 的例子 `src/api/**/*.ts`。嵌套路径、触发文件、规则文件名是夹具自己的。symlink 的 `file_path` 用链接这一侧。目标路径会不会出现在字段里，专项没有写，夹具不解析。

`memory_type` 除了根上那条，其余行夹具也填 `Project`。页上没有把嵌套文件、规则、`AGENTS.md` 逐条映射到 `User` / `Project` / `Local` / `Managed`。

`il_exit2` 和 `il_block_decision` 把 `loaded` 记成 1。`il_additional_context` 的 `additionalContext` 和纯文本 stdout 都不进模型上下文。`il_audit_log` 在钩跑起来时记下 `load_reason` 和 `file_path`。懒加载多记 `trigger_file_path`，`path_glob_match` 多记 `globs`，`include` 多记 `parent_file_path`，`compact` 记下重载。

直接读取的 `AGENTS.md`，`il_fired=0`，审计行是空的，`loaded` 仍是 1。import 那条 `load_reason=include`。

`il_with_if` 把 `if` 写在 `InstructionsLoaded` 上。钩不跑，文件照样在上下文里。`il_env_write` 想写环境变量，`env_persisted=0`。这只事件没有 `CLAUDE_ENV_FILE`。

`sessionstart_compact_stdout` 只在 `compact` 这一次把指南里的那段 echo 记进模型上下文。这是对 [Re-inject context after compaction](https://code.claude.com/docs/en/hooks-guide#re-inject-context-after-compaction) 的模拟。同一只处理器挂在嵌套懒加载上，`sessionstart_fired=0`。`SessionStart` 的 matcher 对的是 `source`，不是 `load_reason`。`startup` 对不上 `session_start`。

空 matcher 在输出里写成 `matcher=empty`。非空只按 `|` 切。不模拟逗号，也不模拟正则。用不上 matcher 的处理器写成 `matcher=na`。事件没开火时 `load_reason=na`。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks#instructionsloaded) 的 InstructionsLoaded 小节、[How Claude remembers your project](https://code.claude.com/docs/en/memory#where-agents-md-differs-from-claude-md) 的对照表，和 [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide#re-inject-context-after-compaction) 的压缩后补上下文例子。

```bash
python3 demos/instructionsloaded-observe/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `eager_il_exit2` | 急加载，exit 2，`loaded=1` |
| `eager_il_block_decision` | 顶层 `decision: "block"`，文件仍在上下文里 |
| `eager_il_additional_context` | `additionalContext` 和 stdout 都不进模型 |
| `eager_il_discarded` | 只有 `continue: false` 和 `systemMessage` |
| `eager_il_with_if` | `InstructionsLoaded` 上写了 `if` |
| `eager_il_env_write` | 没有 `CLAUDE_ENV_FILE`，`env_persisted=0` |
| `eager_none` | 什么都不交，文件仍加载 |
| `eager_matcher_startup` | matcher 写成 `startup`，对不上 `session_start` |
| `nested_il_exit2` | 走进子目录，exit 2，嵌套文件仍加载 |
| `nested_il_audit_log` | 审计记下 `nested_traversal` 和触发文件 |
| `nested_matcher_session_start` | matcher 只写了 `session_start`，懒加载从旁边走过 |
| `path_il_block_decision` | 条件规则，`decision: "block"`，仍加载 |
| `path_il_audit_log` | 审计记下 `path_glob_match` 和 `globs` |
| `compact_il_exit2` | 压缩后重载，exit 2，只是看见 |
| `compact_il_audit_log` | 审计记下 `compact` |
| `compact_il_additional_context` | 观察事件的上下文进不了模型 |
| `compact_sessionstart_compact_stdout` | 模拟指南：`SessionStart` matcher `compact` 的 stdout 能注入 |
| `nested_sessionstart_compact_stdout` | 同一只补提醒钩，看不见懒加载 |
| `agents_direct_il_exit2` | 设置直接读取的 `AGENTS.md`，事件不开火 |
| `agents_direct_il_audit_log` | 审计日志漏掉这一次 |
| `include_il_exit2` | import，exit 2，仍加载 |
| `include_il_audit_log` | `load_reason=include`，记下 `parent_file_path` |
| `symlink_il_exit2` | symlink 按普通 `CLAUDE.md` 急加载开火 |
