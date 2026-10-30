# 订单 + 物流：交接丢掉的字段

本地脚本，演示两条专科子 Agent 的摘要交接，和折成一份技能加两个工具之后的差别。不调用模型，不读密钥，也不跑 [anthropics/single-agent-loop-kit](https://github.com/anthropics/single-agent-loop-kit)。

```bash
python3 demos/fold-subagents-single-loop/run_demo.py
```

通过时最后一行是 `result=pass`。

四条路径共用 `fixtures/` 里的订单 `QS-2048` 和运单 `TRK-20481`：

| 路径 | 在看什么 |
| --- | --- |
| `handoff-drop` | 订单摘要按「只说商品和状态」丢掉运单号，物流拒绝 |
| `handoff-stop` | 摘要里有运单号，编排器拿到摘要就停 |
| `same-context` | 原始 JSON 留在同一个上下文，接着调用 `track_shipment` |
| `early-answer` | 已经折进主循环，却只凭订单状态作答 |
| `tool-refusal` | 不带运单号调用 `track_shipment`，工具拒绝，不编日期 |

`fold_map.json` 把提示词逐行分到技能、工具、参考或删除。这是写死的对照表，用来保证提示词文件和文章里的表一致。它不是模型在读提示词。
