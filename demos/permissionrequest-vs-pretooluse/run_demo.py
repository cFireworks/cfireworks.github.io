#!/usr/bin/env python3
"""伪控制环：PermissionRequest 的 exit 2 不拦截。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
事件名和处理器是夹具。它不是 settings.json 里的 hook，也没有权限弹窗。
exit 2 与 decision.behavior 的结算只转述 Hooks reference 的 per-event 表。
"""

from __future__ import annotations

from dataclasses import dataclass

EVENTS = frozenset({"pre_tool", "permission_request"})
HANDLERS = frozenset({"none", "exit2", "decision_deny", "permission_decision_deny"})


def apply_handler(event: str, handler: str) -> str:
    """exit 2 只在 PreToolUse 上变成 blocked。弹窗事件只认 decision deny。

    permission_decision_deny 是 PreToolUse 的 permissionDecision。
    decision_deny 是 PermissionRequest 的 decision.behavior deny。
    填错事件的形状记成 not_blocked。exit 2 打在弹窗事件上也不拦截。
    """
    if event not in EVENTS:
        raise SystemExit(f"unknown event {event}")
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if event == "pre_tool" and handler in {"exit2", "permission_decision_deny"}:
        return "blocked"
    if event == "permission_request" and handler == "decision_deny":
        return "blocked"
    return "not_blocked"


def settle(dialog: bool, pre: str, request: str) -> tuple[str, str]:
    """返回 (outcome, permission_request)。

    不弹窗时 PermissionRequest 不触发，配在它上面的处理器不会跑。
    PreToolUse 的 exit 2 或 permissionDecision deny 在弹窗之前就拦住。
    """
    if not isinstance(dialog, bool):
        raise SystemExit("dialog must be a bool")
    if apply_handler("pre_tool", pre) == "blocked":
        return "blocked", "never_fired"
    if not dialog:
        return "not_blocked", "never_fired"
    return apply_handler("permission_request", request), "fired"


@dataclass(frozen=True)
class Record:
    name: str
    dialog: bool
    pre: str
    request: str
    outcome: str
    permission_request: str
    note: str

    def line(self) -> str:
        dialog = "yes" if self.dialog else "no"
        return " ".join(
            [
                f"case={self.name}",
                f"dialog={dialog}",
                f"pre={self.pre}",
                f"request={self.request}",
                f"permission_request={self.permission_request}",
                f"outcome={self.outcome}",
                f"note={self.note}",
            ]
        )


def run(name: str, dialog: bool, pre: str, request: str, note: str) -> Record:
    outcome, permission_request = settle(dialog, pre, request)
    return Record(
        name=name,
        dialog=dialog,
        pre=pre,
        request=request,
        outcome=outcome,
        permission_request=permission_request,
        note=note,
    )


def printed_records() -> list[Record]:
    return [
        run(
            "pr_exit2",
            True,
            "none",
            "exit2",
            "exit2_not_honored",
        ),
        run(
            "pr_deny",
            True,
            "none",
            "decision_deny",
            "decision_behavior_deny",
        ),
        run(
            "pre_exit2",
            True,
            "exit2",
            "decision_deny",
            "tool_not_called",
        ),
        run(
            "no_dialog",
            False,
            "none",
            "decision_deny",
            "hook_not_invoked",
        ),
        run(
            "pre_deny",
            True,
            "permission_decision_deny",
            "none",
            "permission_decision_deny",
        ),
    ]


def extra_records() -> list[Record]:
    return [
        run(
            "wrong_shape",
            True,
            "none",
            "permission_decision_deny",
            "pretool_field_on_permission_request",
        ),
        run(
            "wrong_shape_pre",
            True,
            "decision_deny",
            "none",
            "decision_behavior_on_pre_tool",
        ),
        run(
            "no_dialog_pre",
            False,
            "exit2",
            "exit2",
            "pre_tool_still_blocks",
        ),
        run(
            "pr_silent",
            True,
            "none",
            "none",
            "silence_is_not_a_deny",
        ),
    ]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["pr_exit2"],
        outcome="not_blocked",
        permission_request="fired",
        request="exit2",
        note="exit2_not_honored",
    )
    expect(
        records["pr_deny"],
        outcome="blocked",
        permission_request="fired",
        request="decision_deny",
        note="decision_behavior_deny",
    )
    expect(
        records["pre_exit2"],
        outcome="blocked",
        pre="exit2",
        permission_request="never_fired",
        note="tool_not_called",
    )
    expect(
        records["no_dialog"],
        dialog=False,
        outcome="not_blocked",
        permission_request="never_fired",
        request="decision_deny",
        note="hook_not_invoked",
    )
    expect(
        records["pre_deny"],
        outcome="blocked",
        pre="permission_decision_deny",
        permission_request="never_fired",
    )

    expect(
        records["wrong_shape"],
        outcome="not_blocked",
        permission_request="fired",
        request="permission_decision_deny",
    )
    expect(
        records["wrong_shape_pre"],
        outcome="not_blocked",
        permission_request="fired",
        pre="decision_deny",
    )
    expect(
        records["no_dialog_pre"],
        outcome="blocked",
        dialog=False,
        permission_request="never_fired",
        pre="exit2",
    )
    expect(
        records["pr_silent"],
        outcome="not_blocked",
        permission_request="fired",
        note="silence_is_not_a_deny",
    )

    if records["pr_exit2"].outcome == "blocked":
        raise SystemExit("PermissionRequest exit 2 was counted as a block")
    if records["no_dialog"].permission_request != "never_fired":
        raise SystemExit("PermissionRequest fired without a dialog")
    if records["no_dialog"].outcome == "blocked":
        raise SystemExit("a handler that never ran blocked the call")
    if records["pre_exit2"].permission_request == "fired":
        raise SystemExit("PermissionRequest fired after PreToolUse already blocked")

    for record in records.values():
        if record.permission_request == "never_fired" and record.request == "decision_deny":
            if record.outcome == "blocked" and record.pre == "none":
                raise SystemExit(f"{record.name} blocked without running PermissionRequest")
        if record.dialog is False and record.permission_request != "never_fired":
            raise SystemExit(f"{record.name} fired PermissionRequest with no dialog")
        if record.request == "exit2" and record.permission_request == "fired":
            if record.outcome != "not_blocked":
                raise SystemExit(f"{record.name} honored exit 2 on PermissionRequest")
        if record.pre == "exit2" and record.outcome != "blocked":
            raise SystemExit(f"{record.name} let a PreToolUse exit 2 through")

    printed = {records[name].outcome for name in (
        "pr_exit2",
        "pr_deny",
        "pre_exit2",
        "no_dialog",
        "pre_deny",
    )}
    if printed != {"not_blocked", "blocked"}:
        raise SystemExit(f"outcomes {printed}")


def main() -> None:
    records = {row.name: row for row in [*printed_records(), *extra_records()]}
    check(records)
    for row in printed_records():
        print(records[row.name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
