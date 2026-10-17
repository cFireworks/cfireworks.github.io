---
name: compare-experiments
description: 比较两次实验前，先确认 ax 版本和 space，再列出实验并比较。
---

# 比较两次实验

这是本地替身，不连接任何托管服务，也不读取密钥。

1. 运行 `ax --version`。版本打不出来就停。
2. 不知道 space 标识时，运行 `ax spaces list -o json`，从输出里取一个 id。
3. 运行 `ax experiments list --project demo --output json`。
4. 运行 `ax experiments compare --base base-demo --head head-demo`。
5. 只留下退步的例子。不要把整页原始跨度贴进对话。
