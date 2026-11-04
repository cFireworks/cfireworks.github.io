#!/usr/bin/env python3
"""伪控制环：exit 2 只在动作还没发生时变成拦截。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
事件名和信号是夹具。它不是 settings.json 里的 hook，也没有权限弹窗。
exit 2、deny、onFailure block 的结算只转述 Hooks reference 与 hooks guide。
"""

from __future__ import annotations

from dataclasses import dataclass

# 挡得住的是动作还没发生的事件。post_* 触发时，工具或压缩已经完成。
BLOCKABLE = frozenset({"pre_tool", "pre_compact"})
EVENTS = frozenset(
    {"pre_tool", "post_tool", "pre_compact", "post_compact", "session_compact"}
)
SIGNALS = frozenset({"exit0", "exit2", "miss", "miss_block", "deny", "context"})


def settle(event: str, signal: str) -> str:
    """exit 2 只在动作还没发生时变成 blocked。

    miss_block 先改写成 exit 2：onFailure 为 block 时，失败做的是这一事件的 exit 2。
    context 只属于 SessionStart 的 compact。那是 stdout 或 additionalContext，不是退出码。
    deny 只属于 PreToolUse。
    """
    if event not in EVENTS:
        raise SystemExit(f"unknown event {event}")
    if signal not in SIGNALS:
        raise SystemExit(f"unknown signal {signal}")
    if signal == "miss_block":
        signal = "exit2"
    if signal == "context":
        if event != "session_compact":
            raise SystemExit("context is only the SessionStart compact path")
        return "reinjected"
    if signal == "deny":
        if event != "pre_tool":
            raise SystemExit("deny is a PreToolUse decision")
        return "blocked"
    if event == "session_compact":
        return "continues"
    if signal == "exit2" and event in BLOCKABLE:
        return "blocked"
    if signal == "miss" and event == "pre_tool":
        return "allowed"
    if event == "post_tool":
        return "already_ran"
    if event == "post_compact":
        return "already_compacted"
    if event == "pre_compact":
        return "compacts"
    if event == "pre_tool" and signal == "exit0":
        return "proceeds"
    raise SystemExit(f"unhandled {event} {signal}")


@dataclass(frozen=True)
class Record:
    name: str
    event: str
    signal: str
    outcome: str
    note: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"event={self.event}",
                f"signal={self.signal}",
                f"outcome={self.outcome}",
                f"note={self.note}",
            ]
        )


def run(name: str, event: str, signal: str, note: str) -> Record:
    return Record(
        name=name,
        event=event,
        signal=signal,
        outcome=settle(event, signal),
        note=note,
    )


def printed_records() -> list[Record]:
    return [
        run("pre_exit2", "pre_tool", "exit2", "tool_not_called"),
        run("post_exit2", "post_tool", "exit2", "stderr_to_claude"),
        run("policy_miss", "pre_tool", "miss", "script_never_started"),
        run("policy_block", "pre_tool", "miss_block", "on_failure_block"),
        run("compact_block", "pre_compact", "exit2", "compaction_not_started"),
        run("compact_done", "post_compact", "exit2", "stderr_to_user"),
        run("reinject", "session_compact", "context", "stdout_or_additional_context"),
        run("pre_deny", "pre_tool", "deny", "permission_decision_deny"),
    ]


def extra_records() -> list[Record]:
    return [
        run("pre_exit0", "pre_tool", "exit0", "silence_is_not_a_deny"),
        # 参考页写：exit 2 时，合法 JSON 里的 allow 盖不过这次拦截。夹具不解析 JSON，直接按 exit 2 结算。
        run("exit2_allow", "pre_tool", "exit2", "json_allow_does_not_override"),
        run("post_miss_block", "post_tool", "miss_block", "on_failure_does_not_undo"),
        run("compact_miss", "pre_compact", "miss", "fail_open_compaction"),
        run("session_exit2", "session_compact", "exit2", "stderr_to_user_not_claude"),
        run("format_ok", "post_tool", "exit0", "format_is_followup"),
    ]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(records["pre_exit2"], outcome="blocked", event="pre_tool", signal="exit2")
    expect(
        records["post_exit2"],
        outcome="already_ran",
        event="post_tool",
        signal="exit2",
        note="stderr_to_claude",
    )
    expect(records["policy_miss"], outcome="allowed", signal="miss")
    expect(records["policy_block"], outcome="blocked", signal="miss_block")
    expect(records["compact_block"], outcome="blocked", event="pre_compact")
    expect(
        records["compact_done"],
        outcome="already_compacted",
        note="stderr_to_user",
    )
    expect(records["reinject"], outcome="reinjected", signal="context")
    expect(records["pre_deny"], outcome="blocked", signal="deny")

    expect(records["pre_exit0"], outcome="proceeds", note="silence_is_not_a_deny")
    expect(records["exit2_allow"], outcome="blocked", note="json_allow_does_not_override")
    expect(records["post_miss_block"], outcome="already_ran", note="on_failure_does_not_undo")
    expect(records["compact_miss"], outcome="compacts", note="fail_open_compaction")
    expect(records["session_exit2"], outcome="continues", signal="exit2")
    expect(records["format_ok"], outcome="already_ran", note="format_is_followup")

    if records["session_exit2"].outcome == "reinjected":
        raise SystemExit("exit 2 on SessionStart was counted as reinjection")
    if records["reinject"].signal != "context":
        raise SystemExit("reinjection was not the stdout path")

    for record in records.values():
        if record.event == "post_tool" and record.outcome == "blocked":
            raise SystemExit(f"{record.name} blocked a tool that already ran")
        if record.event == "pre_tool" and record.outcome == "already_ran":
            raise SystemExit(f"{record.name} marked a pre-hook as already ran")
        if record.event == "post_compact" and record.outcome == "blocked":
            raise SystemExit(f"{record.name} blocked a compaction that already finished")
        if record.outcome == "reinjected" and record.signal != "context":
            raise SystemExit(f"{record.name} reinjected without context output")

    printed = {records[name].outcome for name in (
        "pre_exit2",
        "post_exit2",
        "policy_miss",
        "policy_block",
        "compact_block",
        "compact_done",
        "reinject",
        "pre_deny",
    )}
    if printed != {
        "blocked",
        "already_ran",
        "allowed",
        "already_compacted",
        "reinjected",
    }:
        raise SystemExit(f"outcomes {printed}")


def main() -> None:
    records = {row.name: row for row in [*printed_records(), *extra_records()]}
    check(records)
    for row in printed_records():
        print(records[row.name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
