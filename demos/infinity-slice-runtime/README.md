# Infinity 切片形状的离线模拟

这个目录不是 Hydro Infinity，也不会部署 Lambda、SQS 或 Aurora。`slice_sim.py` 用内存队列和脚本模型走一遍切片：加载历史、一次补全、异步工具立刻返回、结果稍后入队、重复消息跳过、第二条 `tool_result` 被拒绝、事件写成 `receive_event__injected`。

回调 URL 里的令牌是占位字符串 `inf-demo-not-a-credential`。脚本不访问网络。

打印的 tick 和 `waiting_history_bytes` 是玩具历史自己的大小。Infinity 博文里的约 100 KB、约 7.5 万 agent，不由这个脚本测量。

```bash
python3 demos/infinity-slice-runtime/slice_sim.py
```

成功时最后一行是 `DEMO OK`，进程退出码为 0。
