#!/usr/bin/env python3
"""伪控制环：评估器只读对话，命令闸只看退出码。

不调用 API，不读密钥，不访问网络。
评估器是字符串夹具，不是文档里的 small fast model。
八次来自 Best practices 与 Hooks guide 的字面转述：连拦八次之后，下一次拦被覆盖。
夹具没有在 Claude Code 里数过这一下落在第几下。
"""

from __future__ import annotations

from dataclasses import dataclass

# 夹具标记。必须出现在 transcript 里，模拟评估器从对话得出的「不可能」。
IMPOSSIBLE = "条件无法满足：依赖已从注册表删除"
NEED = ("npm test", "exit 0")
# 页上写的是八次。不设 CLAUDE_CODE_STOP_HOOK_BLOCK_CAP 时的行为，不是我读到的变量默认值字符串。
BLOCK_CAP = 8


def judge_transcript(text: str, need: tuple[str, ...] = NEED) -> str:
    """只读已经写进对话的文本。不跑命令。"""
    if IMPOSSIBLE in text:
        return "impossible"
    if need and all(piece in text for piece in need):
        return "met"
    return "not_yet"


def transcript_of(said: str, tool: str | None = None) -> str:
    lines = []
    if tool:
        lines.append(f"$ {tool}")
    lines.append(said)
    return "\n".join(lines)


def replay_stops(events: tuple[str, ...], *, cap: int = BLOCK_CAP) -> tuple[str, int, int]:
    """回放收工尝试。

    exit2：脚本忽略 stop_hook_active，退出码 2。
    exit2_honor：已有连拦时把旗标当成 true，改为退出码 0。
    exit0：命令本身通过。
    tool：中间有一次工具调用，连拦从零再数。这不是一次收工。

    旗标只在「已经连拦、中间没有工具」时为 true。
    工具调用之后旗标还在不在，打开的指南没有写，这里不猜。
    返回 (判决, 当前连拦, 收工尝试次数)。
    """
    streak = 0
    attempts = 0
    decision = "command_clear"
    for event in events:
        if event == "tool":
            streak = 0
            continue
        attempts += 1
        active = streak > 0
        if event == "exit0":
            decision = "command_clear"
            streak = 0
            continue
        if event == "exit2_honor" and active:
            decision = "allowed_stop_hook_active"
            continue
        if event not in ("exit2", "exit2_honor"):
            raise SystemExit(f"unknown event {event}")
        if streak >= cap:
            return "stop_forced_after_cap", streak, attempts
        streak += 1
        decision = "stop_blocked"
    return decision, streak, attempts


def combine(verdict: str | None, gate: str | None) -> str:
    """夹具政策，不是文档里的 hook 排序。

    exit 2 盖过评估器的 Met。
    命令闸放行，不把 Not yet 改成做完。
    """
    if gate in ("stop_blocked", "stop_forced_after_cap"):
        return gate
    if gate == "allowed_stop_hook_active":
        return gate
    if verdict == "met":
        return "goal_met"
    if verdict == "not_yet":
        return "goal_not_yet"
    if verdict == "impossible":
        return "goal_impossible"
    raise SystemExit(f"no outcome verdict={verdict!r} gate={gate!r}")


@dataclass(frozen=True)
class Record:
    name: str
    outcome: str | None
    evaluator: str | None
    blocks: int
    attempts: int
    note: str
    allowed: str | None = None

    def line(self) -> str:
        parts = [f"case={self.name}"]
        if self.allowed:
            parts.append(f"allowed={self.allowed}")
        else:
            parts.append(f"outcome={self.outcome}")
        if self.evaluator:
            parts.append(f"evaluator={self.evaluator}")
        if self.attempts:
            parts.append(f"blocks={self.blocks}")
            parts.append(f"attempts={self.attempts}")
        parts.append(f"note={self.note}")
        return " ".join(parts)


def goal_only(name: str, said: str, tool: str | None, note: str) -> Record:
    verdict = judge_transcript(transcript_of(said, tool))
    return Record(
        name=name,
        outcome=combine(verdict, None),
        evaluator=verdict,
        blocks=0,
        attempts=0,
        note=note,
    )


def with_gate(
    name: str,
    events: tuple[str, ...],
    note: str,
    said: str = "可以收工",
    tool: str | None = None,
    use_goal: bool = False,
) -> Record:
    verdict = judge_transcript(transcript_of(said, tool)) if use_goal else None
    gate, streak, attempts = replay_stops(events)
    outcome = combine(verdict, gate)
    allowed = outcome if outcome == "allowed_stop_hook_active" else None
    return Record(
        name=name,
        outcome=None if allowed else outcome,
        evaluator=verdict,
        blocks=streak,
        attempts=attempts,
        note=note,
        allowed=allowed,
    )


def printed_records() -> list[Record]:
    return [
        goal_only(
            "claim_only",
            "测过了，可以收工。测试全部通过，exit 0。",
            None,
            "exit_code_without_command",
        ),
        goal_only("evidence", "exit 0", "npm test", "transcript_only"),
        goal_only(
            "gone",
            "条件无法满足：依赖已从注册表删除，装不回来。",
            None,
            "marker_in_transcript",
        ),
        with_gate("tsc_red", ("exit2",), "exit_2"),
        with_gate(
            "met_but_red",
            ("exit2",),
            "exit_2_overrides_met",
            said="exit 0",
            tool="npm test",
            use_goal=True,
        ),
        with_gate("eight_blocks", ("exit2",) * 9, "cap_overrides_next"),
        with_gate("active_flag", ("exit2_honor", "exit2_honor"), "not_a_pass"),
    ]


def extra_records() -> list[Record]:
    return [
        with_gate(
            "both_green",
            ("exit0",),
            "command_exit_0",
            said="exit 0",
            tool="npm test",
            use_goal=True,
        ),
        with_gate(
            "goal_open",
            ("exit0",),
            "command_exit_0_goal_open",
            said="测过了，exit 0。",
            use_goal=True,
        ),
        with_gate(
            "reset_on_tool",
            ("exit2", "exit2", "exit2", "tool", "exit2", "exit2", "exit2"),
            "streak_reset",
        ),
        goal_only(
            "marker_wins",
            "条件无法满足：依赖已从注册表删除\nnpm test\nexit 0",
            "npm test",
            "fixture_priority",
        ),
    ]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["claim_only"],
        outcome="goal_not_yet",
        evaluator="not_yet",
        note="exit_code_without_command",
    )
    expect(records["evidence"], outcome="goal_met", evaluator="met", attempts=0)
    expect(records["gone"], outcome="goal_impossible", evaluator="impossible")
    expect(records["tsc_red"], outcome="stop_blocked", evaluator=None, blocks=1, attempts=1)
    expect(
        records["met_but_red"],
        outcome="stop_blocked",
        evaluator="met",
        blocks=1,
        attempts=1,
        note="exit_2_overrides_met",
    )
    expect(
        records["eight_blocks"],
        outcome="stop_forced_after_cap",
        blocks=8,
        attempts=9,
        note="cap_overrides_next",
    )
    expect(
        records["active_flag"],
        outcome=None,
        allowed="allowed_stop_hook_active",
        blocks=1,
        attempts=2,
        note="not_a_pass",
    )
    expect(records["both_green"], outcome="goal_met", evaluator="met", note="command_exit_0")
    expect(
        records["goal_open"],
        outcome="goal_not_yet",
        evaluator="not_yet",
        note="command_exit_0_goal_open",
    )
    expect(records["reset_on_tool"], outcome="stop_blocked", blocks=3, attempts=6)
    expect(records["marker_wins"], outcome="goal_impossible", evaluator="impossible")

    printed = {
        records[name].outcome
        for name in (
            "claim_only",
            "evidence",
            "gone",
            "tsc_red",
            "met_but_red",
            "eight_blocks",
        )
    }
    if printed != {
        "goal_met",
        "goal_not_yet",
        "goal_impossible",
        "stop_blocked",
        "stop_forced_after_cap",
    }:
        raise SystemExit(f"outcomes {printed}")
    if records["active_flag"].allowed != "allowed_stop_hook_active":
        raise SystemExit("active_flag counted as a pass")


def main() -> None:
    records = {row.name: row for row in [*printed_records(), *extra_records()]}
    check(records)
    for row in printed_records():
        print(records[row.name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
