#!/usr/bin/env python3
"""离线切片模拟。

这不是 Hydro Infinity 运行时，也不连接 AWS。它只复现 AWS 博文和
hydro-project/infinity@341f6c2 里能讲清的形状：

- 每个 thread 一条 FIFO
- 一次 step：加载历史、脚本模型做一次补全、异步工具至多派发一次，然后结束
- execute 只登记外部工作并立刻返回；结果稍后入队
- 同一工具调用的第二条 tool_result 被拒绝
- 后续事件写成 receive_event__injected
- 已处理的消息 id 再次投递会被跳过
- 外部副作用另用幂等键

占位令牌只出现在回调 URL 字符串里，脚本不发起网络请求。
打印出的 tick 和字节数是这份玩具历史自己的账，不是 Infinity 的内存基准。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

FAKE_CALLBACK_TOKEN = "inf-demo-not-a-credential"
INJECTED = "receive_event__injected"


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


@dataclass
class Hist:
    role: str
    text: str
    name: str | None = None
    call_id: str | None = None
    arguments: dict | None = None


@dataclass
class QueueMsg:
    msg_id: str
    group_id: str
    kind: str  # user | tool_result | event
    text: str
    call_id: str | None = None
    original_tool_name: str | None = None
    original_args: dict | None = None


@dataclass
class Decision:
    kind: str  # text | tool
    text: str = ""
    name: str = ""
    arguments: dict = field(default_factory=dict)
    call_id: str = ""
    sync: bool = False


def scripted_model(history: list[Hist]) -> Decision:
    """固定剧本，代替模型。不读取令牌，不访问网络。"""
    last = history[-1]
    if last.role == "user" and "build" in last.text:
        return Decision(
            "tool",
            name="get_build_status",
            arguments={"build_id": "42"},
            call_id="call_build",
        )
    if last.role == "tool_result" and last.call_id == "call_build":
        return Decision("text", text="Build 42: green")
    if last.role == "user" and last.text.startswith("subscribe"):
        return Decision(
            "tool",
            name="subscribe_github_events",
            arguments={"owner": "acme", "repo": "api"},
            call_id="call_sub",
        )
    if last.role == "tool_result" and last.call_id == "call_sub" and last.name != INJECTED:
        return Decision("text", text="订阅已记下，先休眠")
    if last.role == "tool_result" and last.name == INJECTED:
        return Decision("text", text=f"事件已读：{last.text}")
    if last.role == "user" and "review" in last.text:
        return Decision(
            "tool",
            name="spawn_thread",
            arguments={"instructions": "Review src/auth.ts"},
            call_id="call_spawn",
            sync=True,
        )
    if last.role == "tool_result" and last.call_id == "call_spawn" and last.name != INJECTED:
        return Decision("text", text="子线程已创建，父线程继续")
    raise SystemExit(f"FAIL 剧本没有覆盖最后一条：{last}")


class SliceSim:
    def __init__(self) -> None:
        self.history: dict[str, list[Hist]] = {}
        self.processed: dict[str, set[str]] = {}
        self.queues: dict[str, list[QueueMsg]] = {}
        self.slot: str | None = None
        self.slot_ticks = 0
        self.idle_ticks = 0
        self.skipped = 0
        self.dispatches: list[str] = []
        self.jobs: list[str] = []
        self.trace: list[str] = []

    def enqueue(self, msg: QueueMsg) -> None:
        if msg.kind == "tool_result":
            self._reject_second_result(msg)
        self.queues.setdefault(msg.group_id, []).append(msg)

    def _reject_second_result(self, msg: QueueMsg) -> None:
        require(msg.call_id is not None, "tool_result 缺少 call_id")
        for old in self.queues.get(msg.group_id, []):
            if old.kind == "tool_result" and old.call_id == msg.call_id:
                raise RuntimeError(f"duplicate tool_result for {msg.call_id}")
        for item in self.history.get(msg.group_id, []):
            if item.role == "tool_result" and item.call_id == msg.call_id and item.name != INJECTED:
                raise RuntimeError(f"duplicate tool_result for {msg.call_id}")

    def history_bytes(self, group_id: str) -> int:
        payload = [
            {
                "role": item.role,
                "text": item.text,
                "name": item.name,
                "call_id": item.call_id,
                "arguments": item.arguments,
            }
            for item in self.history.get(group_id, [])
        ]
        return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def step(self, group_id: str) -> str:
        queue = self.queues.get(group_id, [])
        require(queue, f"{group_id} 没有待处理消息")
        msg = queue.pop(0)
        seen = self.processed.setdefault(group_id, set())
        if msg.msg_id in seen:
            self.skipped += 1
            self.trace.append(f"skip {msg.msg_id}")
            return "skipped"

        self.slot = group_id
        self.slot_ticks += 1

        history = self.history.setdefault(group_id, [])
        if msg.kind == "event":
            new_id = f"inj_{msg.msg_id}"
            history.append(
                Hist(
                    role="tool_call",
                    text=INJECTED,
                    name=INJECTED,
                    call_id=new_id,
                    arguments={
                        "original_tool_name": msg.original_tool_name,
                        "original_tool_call_id": msg.call_id,
                        "original_args": msg.original_args,
                    },
                )
            )
            history.append(
                Hist(
                    role="tool_result",
                    text=msg.text,
                    name=INJECTED,
                    call_id=new_id,
                )
            )
        elif msg.kind == "tool_result":
            history.append(
                Hist(
                    role="tool_result",
                    text=msg.text,
                    name="tool_result",
                    call_id=msg.call_id,
                )
            )
        else:
            history.append(Hist(role="user", text=msg.text))
        seen.add(msg.msg_id)

        for _ in range(4):
            decision = scripted_model(history)
            if decision.kind == "text":
                history.append(Hist(role="assistant", text=decision.text))
                self.trace.append(f"text {group_id}: {decision.text}")
                break
            if decision.name == INJECTED:
                raise SystemExit("FAIL 剧本试图自己调用 receive_event__injected")
            history.append(
                Hist(
                    role="tool_call",
                    text=decision.name,
                    name=decision.name,
                    call_id=decision.call_id,
                    arguments=decision.arguments,
                )
            )
            if decision.sync:
                history.append(
                    Hist(
                        role="tool_result",
                        text="Child thread is spawned: thread_a1b2",
                        name="spawn_thread",
                        call_id=decision.call_id,
                    )
                )
                self.trace.append(f"sync {decision.name}")
                continue
            self.dispatches.append(decision.name)
            self.trace.append(f"dispatch {decision.name} then yield")
            break
        else:
            raise SystemExit("FAIL 同步回路没有结束")

        self.slot = None
        return "yielded"

    def wait_idle(self, ticks: int, group_id: str) -> None:
        require(self.slot is None, "等待期间切片仍占着槽位")
        self.idle_ticks += ticks
        self.trace.append(
            f"idle {ticks} ticks, history_bytes={self.history_bytes(group_id)}, slot=None"
        )


def execute_build(sim: SliceSim, build_id: str) -> str:
    """工具只启动工作。返回值是受理，不是构建结果。"""
    sim.jobs.append(build_id)
    return "accepted"


def deliver_build(sim: SliceSim, group_id: str, build_id: str, dedup_id: str) -> None:
    sim.enqueue(
        QueueMsg(
            msg_id=dedup_id,
            group_id=group_id,
            kind="tool_result",
            text=f"Build {build_id}: green",
            call_id="call_build",
        )
    )


def external_effect(store: dict[str, int], key: str | None) -> None:
    if key is None:
        store["fires"] = store.get("fires", 0) + 1
        return
    if key in store:
        return
    store[key] = 1
    store["fires"] = store.get("fires", 0) + 1


def run() -> None:
    sim = SliceSim()
    group = "thread_main"
    callback = f"https://example.invalid/rap?token={FAKE_CALLBACK_TOKEN}"
    require("inf-demo-not-a-credential" in callback, "占位令牌应该留在回调字符串里")
    require(not callback.startswith("https://sqs."), "演示不使用真实队列 URL")

    sim.enqueue(QueueMsg("m1", group, "user", "Is build 42 green yet?"))
    sim.step(group)
    require(sim.dispatches == ["get_build_status"], "第一刀应该派发构建查询")
    require(execute_build(sim, "42") == "accepted", "execute 应立刻受理")
    require(sim.slot is None, "派发后槽位应释放")
    waiting_bytes = sim.history_bytes(group)
    sim.wait_idle(3, group)
    require(sim.jobs == ["42"], "等待期间工作只登记了一次")

    # 同一条用户消息被重新投递：切片跳过，不再派发。
    sim.enqueue(QueueMsg("m1", group, "user", "Is build 42 green yet?"))
    require(sim.step(group) == "skipped", "重复消息应跳过")
    require(sim.dispatches == ["get_build_status"], "重投不应再次派发工具")

    deliver_build(sim, group, "42", "result_build")
    try:
        deliver_build(sim, group, "42", "result_build_dup")
        raise SystemExit("FAIL 第二条 tool_result 应被拒绝")
    except RuntimeError as exc:
        require("duplicate tool_result" in str(exc), str(exc))
        sim.trace.append("rejected second tool_result for call_build")

    sim.step(group)
    texts = [item.text for item in sim.history[group] if item.role == "assistant"]
    require("Build 42: green" in texts, "结果到达后才有结论")
    require(sim.slot_ticks == 2, f"异步路径应只占 2 个切片 tick，实际 {sim.slot_ticks}")
    require(sim.idle_ticks == 3, "等待的 3 个 tick 不应占槽位")

    # 阻塞循环的对照只存在于打印里：同样 3 个等待 tick 会算进占用。
    blocking_held = sim.slot_ticks + sim.idle_ticks
    slice_held = sim.slot_ticks

    # 订阅：第一条结果占住原 call；后续事件走合成调用。
    sub = "thread_sub"
    sim.enqueue(QueueMsg("s1", sub, "user", "subscribe acme/api"))
    sim.step(sub)
    sim.enqueue(
        QueueMsg(
            "s1r",
            sub,
            "tool_result",
            "Subscribed. Subscription ID: sub_abc",
            call_id="call_sub",
        )
    )
    sim.step(sub)
    sim.enqueue(
        QueueMsg(
            "ev1",
            sub,
            "event",
            '{"event_type":"pull_request","action":"opened","number":42}',
            call_id="call_sub",
            original_tool_name="subscribe_github_events",
            original_args={"owner": "acme", "repo": "api"},
        )
    )
    sim.step(sub)
    injected = [
        item
        for item in sim.history[sub]
        if item.name == INJECTED and item.role == "tool_call"
    ]
    require(len(injected) == 1, "事件应变成一次合成工具调用")
    require(
        injected[0].arguments
        == {
            "original_tool_name": "subscribe_github_events",
            "original_tool_call_id": "call_sub",
            "original_args": {"owner": "acme", "repo": "api"},
        },
        "合成调用应带回原来的工具名、调用 id 和参数",
    )
    original_results = [
        item
        for item in sim.history[sub]
        if item.role == "tool_result" and item.call_id == "call_sub"
    ]
    require(len(original_results) == 1, "原订阅调用仍然只有一条结果")

    # 父线程：spawn 在切片内同步写回，子线程报告以后以事件回来。
    parent = "thread_parent"
    sim.enqueue(QueueMsg("p1", parent, "user", "review src/auth.ts"))
    sim.step(parent)
    require("spawn_thread" not in sim.dispatches, "同步 spawn 不应走异步派发")
    sim.enqueue(
        QueueMsg(
            "p_report",
            parent,
            "event",
            "Report from child thread: Critical: SQL injection in auth.ts line 42.",
            call_id="call_spawn",
            original_tool_name="spawn_thread",
            original_args={"instructions": "Review src/auth.ts"},
        )
    )
    sim.step(parent)
    parent_injected = [
        item
        for item in sim.history[parent]
        if item.role == "tool_call" and item.name == INJECTED
    ]
    require(len(parent_injected) == 1, "子线程报告应锚回 spawn_thread")
    require(
        parent_injected[0].arguments["original_tool_call_id"] == "call_spawn",
        "报告应引用原来的 spawn 调用",
    )

    keyed: dict[str, int] = {}
    external_effect(keyed, "charge-42")
    external_effect(keyed, "charge-42")
    unkeyed: dict[str, int] = {}
    external_effect(unkeyed, None)
    external_effect(unkeyed, None)
    require(keyed["fires"] == 1, "有幂等键的外部副作用只发生一次")
    require(unkeyed["fires"] == 2, "没有幂等键时，重试会再执行一次")

    print("callback", callback)
    print("blocking_slot_ticks", blocking_held)
    print("slice_slot_ticks", slice_held)
    print("idle_ticks_history_only", sim.idle_ticks)
    print("waiting_history_bytes", waiting_bytes)
    print("redelivery_skipped", sim.skipped)
    print("async_dispatches", ",".join(sim.dispatches))
    print("external_effect_with_key", keyed["fires"])
    print("external_effect_without_key", unkeyed["fires"])
    print("trace:")
    for line in sim.trace:
        print(" ", line)
    print("DEMO OK")


if __name__ == "__main__":
    run()
