# 评估器看对话，命令闸看退出码

本地脚本。伪 builder 把一句话留在 transcript 里。伪评估器只在这段文本里找证据，不读仓库。命令闸只看夹具里的退出码：2 打回，0 不把「还没满足」改成做完。

不调用 API，不读密钥，不访问网络。八次来自 [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices) 和 [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide) 的字面：连拦八次之后，下一次拦被覆盖。夹具没有在 Claude Code 里数过这一次落在第几下。

```bash
python3 demos/goal-vs-stop-hook/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `claim_only` | 说测过了，还写了 `exit 0`，transcript 里没有 `npm test` |
| `evidence` | 对话里有命令和 `exit 0` |
| `gone` | 对话里有「条件无法满足」这句夹具标记 |
| `tsc_red` | 只开命令闸，第一次 exit 2 |
| `met_but_red` | 评估器会判 Met，命令闸仍是 2 |
| `eight_blocks` | 连续 exit 2，中间无工具，不走早退 |
| `active_flag` | 第二次把 `stop_hook_active` 当成 true，exit 0。不记成检查通过 |

`both_green`、`goal_open`、`reset_on_tool`、`marker_wins` 只在断言里。证据和「不可能」标记同时在时，夹具取不可能。这是夹具优先级。两层谁先谁后，打开的文档没有写。
