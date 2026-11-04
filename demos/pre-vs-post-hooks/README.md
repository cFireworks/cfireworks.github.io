# 能拦的是动作之前

本地脚本。伪事件是 `pre_tool`、`post_tool`、`pre_compact`、`post_compact`、`session_compact`。伪信号是 `exit0`、`exit2`、`miss`、`miss_block`、`deny`、`context`。

`pre_tool` 加上 exit 2，结局是 `blocked`。`post_tool` 加上 exit 2，结局是 `already_ran`。脚本没启动、又没写 `onFailure: "block"`，结局是 `allowed`。同一失败加上 `miss_block`，按这一事件的 exit 2 结算，工具调用变成 `blocked`。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。夹具不是 settings 里的 hook。退出码语义来自 [Hooks reference](https://code.claude.com/docs/en/hooks) 和 [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide)。

```bash
python3 demos/pre-vs-post-hooks/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `pre_exit2` | 工具还没跑，exit 2 |
| `post_exit2` | 工具已经跑完，exit 2。stderr 记给模型 |
| `policy_miss` | 策略脚本没启动，失败默认放行 |
| `policy_block` | 同一只脚本没启动，`onFailure` 为 block |
| `compact_block` | 压缩还没开始，exit 2 |
| `compact_done` | 压缩已经完成，exit 2。stderr 记给用户 |
| `reinject` | `SessionStart` 的 compact，打出上下文 |
| `pre_deny` | exit 0，`permissionDecision` 为 deny |

`pre_exit0`、`exit2_allow`、`post_miss_block`、`compact_miss`、`session_exit2`、`format_ok` 只在断言里。事后的失败即使写成 block，也不会变成 `blocked`。`SessionStart` 的 exit 2 不会被记成 `reinjected`。
