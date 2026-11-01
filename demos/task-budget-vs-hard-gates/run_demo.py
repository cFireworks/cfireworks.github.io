#!/usr/bin/env python3
"""伪 agent 循环：软倒计时给模型看，硬闸在宿主机。

不调用 Messages API，不读密钥，不访问网络。
doc_replay 的 token 是 Task budgets 文档示例里的约数，用来对账，不是测量。
其余夹具的美元和步数只为把分支分开。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    generated: int
    tool_result: int
    payload: int
    usd_cents: int
    final: bool = False
    interruptible: bool = True

    @property
    def counted(self) -> int:
        return self.generated + self.tool_result


@dataclass(frozen=True)
class Case:
    name: str
    soft_total: int
    steps: tuple[Step, ...]
    max_turns: int | None = None
    max_usd_cents: int | None = None
    mirror_remaining: bool = False
    wall_before_turn: int | None = None


@dataclass(frozen=True)
class Record:
    name: str
    outcome: str | None
    counted: int
    payload: int
    usd_cents: int
    turns: int
    soft: int
    note: str
    final_text: bool
    host_stop: str | None = None
    rejected: str | None = None

    def line(self) -> str:
        if self.rejected:
            return f"case={self.name} rejected={self.rejected}"
        if self.host_stop:
            return (
                f"case={self.name} host_stop={self.host_stop} "
                f"turns={self.turns} note={self.note}"
            )
        return (
            f"case={self.name} outcome={self.outcome} counted={self.counted} "
            f"payload={self.payload} usd_cents={self.usd_cents} turns={self.turns} "
            f"soft={self.soft} final_text={int(self.final_text)} note={self.note}"
        )


def classify_after_response(
    counted: int, soft_total: int, usd_cents: int, max_usd_cents: int | None
) -> str | None:
    """响应已经落地再判硬闸。软预算被越过，不改写美元结局。"""
    if max_usd_cents is not None and usd_cents >= max_usd_cents:
        return "error_max_budget"
    if counted > soft_total:
        return "budget_soft_exceeded"
    return None


def turns_blocked(turns_done: int, max_turns: int | None) -> bool:
    """少留的那一轮收尾在派发前被掐掉，不会有最终文本。0 和不设一样，不限。"""
    if max_turns in (None, 0):
        return False
    return turns_done >= max_turns


def run_case(case: Case) -> Record:
    if case.max_usd_cents == 0:
        return Record(
            name=case.name,
            outcome=None,
            counted=0,
            payload=0,
            usd_cents=0,
            turns=0,
            soft=case.soft_total,
            note="session_never_starts",
            final_text=False,
            rejected="max_budget_usd_zero",
        )

    counted = 0
    payload = 0
    usd_cents = 0
    turns = 0
    mirrored = case.soft_total
    final_text = False
    soft_blown = False

    for step in case.steps:
        if case.wall_before_turn is not None and turns == case.wall_before_turn:
            return Record(
                name=case.name,
                outcome=None,
                counted=counted,
                payload=payload,
                usd_cents=usd_cents,
                turns=turns,
                soft=case.soft_total,
                note="stopped_before_dispatch",
                final_text=final_text,
                host_stop="wall_clock",
            )
        if turns_blocked(turns, case.max_turns):
            return Record(
                name=case.name,
                outcome="error_max_turns",
                counted=counted,
                payload=payload,
                usd_cents=usd_cents,
                turns=turns,
                soft=case.soft_total,
                note="no_final_text",
                final_text=False,
            )

        visible = mirrored if case.mirror_remaining else case.soft_total - counted
        if step.interruptible and visible < step.counted:
            note = (
                "early_by_mirrored_remaining"
                if case.mirror_remaining
                else "paced_stop"
            )
            outcome = "budget_soft_exceeded" if counted > case.soft_total else "success"
            return Record(
                name=case.name,
                outcome=outcome,
                counted=counted,
                payload=payload,
                usd_cents=usd_cents,
                turns=turns,
                soft=case.soft_total,
                note=note,
                final_text=final_text,
            )

        counted += step.counted
        payload += step.payload
        usd_cents += step.usd_cents
        turns += 1
        mirrored -= step.payload
        if step.final:
            final_text = True
        if counted > case.soft_total:
            soft_blown = True

        hard = classify_after_response(
            counted, case.soft_total, usd_cents, case.max_usd_cents
        )
        if hard == "error_max_budget":
            # 触顶的这一响已经计入费用。SDK 的错误结果没有 result，不能当成功答案交出去。
            return Record(
                name=case.name,
                outcome="error_max_budget",
                counted=counted,
                payload=payload,
                usd_cents=usd_cents,
                turns=turns,
                soft=case.soft_total,
                note="one_response_headroom",
                final_text=False,
            )
        if step.final:
            break

    if soft_blown or counted > case.soft_total:
        outcome = "budget_soft_exceeded"
        note = "advisory_overshoot"
    else:
        outcome = "success"
        note = "within_soft"
    return Record(
        name=case.name,
        outcome=outcome,
        counted=counted,
        payload=payload,
        usd_cents=usd_cents,
        turns=turns,
        soft=case.soft_total,
        note=note,
        final_text=final_text,
    )


# 文档示例的三步约数。计入预算的是新生成和新工具结果，重发的历史不重复计。
DOC_STEPS = (
    Step(generated=5000, tool_result=0, payload=20, usd_cents=1),
    Step(generated=4000, tool_result=2800, payload=7800, usd_cents=1),
    Step(generated=6000, tool_result=1200, payload=13000, usd_cents=1, final=True),
)

FINISH_STEPS = (
    Step(generated=12000, tool_result=3000, payload=15000, usd_cents=2),
    Step(
        generated=5000,
        tool_result=3000,
        payload=8000,
        usd_cents=2,
        interruptible=False,
    ),
)

TURN_STEPS = (
    Step(generated=1000, tool_result=0, payload=1000, usd_cents=1),
    Step(generated=1000, tool_result=0, payload=2000, usd_cents=1),
    Step(generated=1000, tool_result=0, payload=3000, usd_cents=1, final=True),
)

USD_STEPS = (
    Step(generated=1000, tool_result=0, payload=1000, usd_cents=4),
    Step(generated=1000, tool_result=0, payload=2000, usd_cents=4, final=True),
)

MIRROR_STEPS = (
    Step(generated=8000, tool_result=0, payload=8000, usd_cents=1),
    Step(generated=5000, tool_result=3000, payload=16000, usd_cents=1),
    Step(generated=6000, tool_result=2000, payload=28000, usd_cents=1, final=True),
)


def printed_cases() -> list[Case]:
    return [
        Case("doc_replay", 100_000, DOC_STEPS, max_turns=10, max_usd_cents=100),
        Case("finish_action", 20_000, FINISH_STEPS, max_turns=10, max_usd_cents=100),
        Case("turn_cap", 100_000, TURN_STEPS, max_turns=2, max_usd_cents=100),
        Case("usd_cap", 100_000, USD_STEPS, max_turns=10, max_usd_cents=5),
        Case(
            "mirror_remaining",
            30_000,
            MIRROR_STEPS,
            max_turns=10,
            max_usd_cents=100,
            mirror_remaining=True,
        ),
        Case("both_gates", 20_000, FINISH_STEPS, max_turns=10, max_usd_cents=3),
    ]


def extra_cases() -> list[Case]:
    return [
        Case("zero_usd", 20_000, DOC_STEPS, max_usd_cents=0),
        Case("zero_turns", 100_000, DOC_STEPS, max_turns=0, max_usd_cents=100),
        Case(
            "clock",
            100_000,
            DOC_STEPS,
            max_turns=10,
            max_usd_cents=100,
            wall_before_turn=1,
        ),
        Case(
            "mirror_off",
            30_000,
            MIRROR_STEPS,
            max_turns=10,
            max_usd_cents=100,
            mirror_remaining=False,
        ),
    ]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["doc_replay"],
        outcome="success",
        counted=19_000,
        payload=20_820,
        turns=3,
        final_text=True,
        note="within_soft",
    )
    expect(
        records["finish_action"],
        outcome="budget_soft_exceeded",
        counted=23_000,
        turns=2,
        note="advisory_overshoot",
    )
    expect(
        records["turn_cap"],
        outcome="error_max_turns",
        turns=2,
        final_text=False,
        note="no_final_text",
    )
    expect(
        records["usd_cap"],
        outcome="error_max_budget",
        usd_cents=8,
        turns=2,
        counted=2_000,
        final_text=False,
        note="one_response_headroom",
    )
    expect(
        records["mirror_remaining"],
        outcome="success",
        counted=16_000,
        turns=2,
        final_text=False,
        note="early_by_mirrored_remaining",
    )
    expect(
        records["both_gates"],
        outcome="error_max_budget",
        counted=23_000,
        usd_cents=4,
        note="one_response_headroom",
    )
    expect(records["zero_usd"], rejected="max_budget_usd_zero", outcome=None)
    expect(
        records["zero_turns"],
        outcome="success",
        turns=3,
        counted=19_000,
        note="within_soft",
    )
    expect(records["clock"], host_stop="wall_clock", outcome=None, turns=1)
    expect(
        records["mirror_off"],
        outcome="success",
        counted=24_000,
        turns=3,
        final_text=True,
        note="within_soft",
    )
    printed = {records[name].outcome for name in (
        "doc_replay",
        "finish_action",
        "turn_cap",
        "usd_cap",
    )}
    if printed != {
        "success",
        "budget_soft_exceeded",
        "error_max_turns",
        "error_max_budget",
    }:
        raise SystemExit(f"outcomes {printed}")


def main() -> None:
    records = {case.name: run_case(case) for case in [*printed_cases(), *extra_cases()]}
    check(records)
    for case in printed_cases():
        print(records[case.name].line())
    print(records["clock"].line())
    print(records["zero_usd"].line())
    print("result=pass")


if __name__ == "__main__":
    main()
