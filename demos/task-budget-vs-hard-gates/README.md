# 软预算提示，硬闸在环外

本地脚本，模拟一条 agent 循环。软倒计时只影响「这一步要不要自觉停」。轮次、美元和墙上时钟在派发前或响应落地后由宿主机判断。

不调用 Messages API，不读密钥，不访问网络。`doc_replay` 的 token 是 [Task budgets](https://platform.claude.com/docs/en/build-with-claude/task-budgets) 文档示例里的约数，用来对账。其余美元和步数是夹具。

```bash
python3 demos/task-budget-vs-hard-gates/run_demo.py
```

通过时最后一行是 `result=pass`。

| 夹具 | 在看什么 |
| --- | --- |
| `doc_replay` | 三请求计入 19000，发出 20820，软预算 100000，正常做完 |
| `finish_action` | 软预算 20000，第二步标成做完比打断好，计入越过，轮次和美元未到 |
| `turn_cap` | 两次工具后还有一句收尾，`max_turns=2`，收尾不会发出 |
| `usd_cap` | 上限 5 美分，两步各 4 美分，第二步做完后是 8 |
| `mirror_remaining` | 客户端按 payload 减 remaining，真计入仍低于软预算，提前停 |
| `both_gates` | 同一响既越过软预算又越过美元上限，结局取美元闸 |
| `clock` | 第二步派发前按墙上时钟停。这不是 SDK 的 subtype |
| `zero_usd` | `max_budget_usd` 为 0，循环不开始 |

`max_turns=0` 在断言里等同于不限，不另打一行。SDK 的花费 subtype 是 `error_max_budget_usd`。这里打印短名 `error_max_budget`。`budget_soft_exceeded` 是夹具栏位：文档写 API 不会在预算处停下，响应里也没有 remaining。
