#!/usr/bin/env python3
"""伪控制环：压缩之前 PreCompact 能拦，或把 stdout 交给摘要器；压完之后补不回。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
假一次 manual，一次限额前的 auto，一次限额错误恢复的 auto。
限额前 / 限额错误恢复不是 hook 输入字段。参考页没有这个字段。
夹具用 kind 模拟 PreCompact 小节写的两种后果。
处理器是 pre_exit2、pre_block_decision、pre_stdout_instructions、
post_only、sessionstart_compact、none。
另有一只 pre_discarded_fields：continue 和 systemMessage 不拦。
超长 stdout、写了 if、matcher 对不上，各走一条。
"""

from __future__ import annotations

from dataclasses import dataclass

CAP = 10_000
# 参考页写超出上限会截断并追加标记。标记原文那一小节没有给出。
# 下面这个标记是夹具自己的，只证明截断发生了。
FIXTURE_MARKER = "[fixture truncated]"

HANDLERS = frozenset(
    {
        "none",
        "pre_exit2",
        "pre_block_decision",
        "pre_stdout_instructions",
        "pre_discarded_fields",
        "post_only",
        "sessionstart_compact",
    }
)
PRE_HANDLERS = frozenset(
    {
        "pre_exit2",
        "pre_block_decision",
        "pre_stdout_instructions",
        "pre_discarded_fields",
    }
)
KINDS = frozenset({"manual", "auto_before_limit", "auto_limit_error"})
SHORT_INSTRUCTION = "摘要里保留未收工的检查清单"
REINJECT_TEXT = "压缩后仍有效：未收工的检查清单"
# Exit code 0 那一节点名的去向。PostCompact 不在前两列。
STDOUT_TO_MODEL = frozenset(
    {
        "UserPromptSubmit",
        "UserPromptExpansion",
        "SessionStart",
        "PostModelSwitch",
    }
)
STDOUT_TO_SUMMARY = frozenset({"PreCompact"})


def trigger_of(kind: str) -> str:
    if kind == "manual":
        return "manual"
    if kind in ("auto_before_limit", "auto_limit_error"):
        return "auto"
    raise SystemExit(f"unknown kind {kind}")


def custom_instructions(kind: str) -> str | None:
    """manual 时是用户传给 /compact 的内容。auto 恒为 null。"""
    if kind not in KINDS:
        raise SystemExit(f"unknown kind {kind}")
    if trigger_of(kind) == "auto":
        return None
    return "保留检查清单"


def matcher_hits(matcher: str, value: str) -> bool:
    """空 matcher 对上每一次。非空只按 `|` 切开。

    参考页写多数事件也接受逗号。夹具不模拟逗号，也不模拟正则。
    """
    if matcher == "":
        return True
    parts = [part.strip() for part in matcher.split("|")]
    return value in parts


def matcher_label(matcher: str) -> str:
    if matcher == "":
        return "empty"
    return matcher


def match_target(handler: str, kind: str) -> str:
    """PreCompact / PostCompact 对 trigger。SessionStart 对 source=compact。"""
    if handler == "sessionstart_compact":
        return "compact"
    return trigger_of(kind)


def blocks(code: int, payload: dict | None) -> bool:
    """exit 2 或顶层 decision block 才拦压缩。

    continue、systemMessage、单独的 reason 不读。
    """
    if code == 2:
        return True
    if isinstance(payload, dict) and payload.get("decision") == "block":
        return True
    return False


def outcome(kind: str, blocked: bool) -> tuple[int, int, int]:
    """返回 compacted, request_failed, continued。

    没拦住：压缩发生，请求不失败。
    manual，或限额前的 auto：拦住就跳过，会话未压缩继续。
    限额错误恢复的 auto：拦住则当前请求失败。
    这是对 Hooks reference 里 PreCompact 那两句的模拟，不是 Claude Code。
    """
    if kind not in KINDS:
        raise SystemExit(f"unknown kind {kind}")
    if not blocked:
        return 1, 0, 1
    if kind == "auto_limit_error":
        return 0, 1, 0
    return 0, 0, 1


def clip(text: str) -> tuple[str, int]:
    """超过 10,000 字符则截到上限，再追加夹具标记。正好 10,000 不截。"""
    if len(text) <= CAP:
        return text, 0
    return text[:CAP] + FIXTURE_MARKER, 1


def long_instruction() -> str:
    tail = "TAIL"
    pad = CAP + len(tail) - len("清单")
    text = "清单" + ("x" * (pad - len(tail))) + tail
    if len(text) <= CAP or "TAIL" not in text[CAP:]:
        raise SystemExit("long instruction fixture drifted")
    return text


def plain_stdout_destination(event: str) -> str:
    """Exit code 0 那一节：谁的纯文本 stdout 进模型，谁变成摘要指令。"""
    if event in STDOUT_TO_SUMMARY:
        return "summary_instructions"
    if event in STDOUT_TO_MODEL:
        return "model_context"
    return "debug_log"


def handler_output(handler: str, long_stdout: bool = False) -> tuple[int, dict | None, str, str]:
    """返回退出码、JSON、stderr、stdout。"""
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if long_stdout and handler != "pre_stdout_instructions":
        raise SystemExit("long stdout only applies to pre_stdout_instructions")
    if handler == "pre_exit2":
        return 2, None, "关键状态还没落盘，先别压", ""
    if handler == "pre_block_decision":
        return 0, {
            "decision": "block",
            "reason": "未落盘的检查清单还在",
            "systemMessage": "已拦截",
            "continue": False,
        }, "", ""
    if handler == "pre_stdout_instructions":
        text = long_instruction() if long_stdout else SHORT_INSTRUCTION
        return 0, None, "", text
    if handler == "pre_discarded_fields":
        return 0, {
            "systemMessage": "已拦截",
            "continue": False,
            "reason": "没有 decision 就不拦",
        }, "", ""
    if handler == "post_only":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PostCompact",
                "additionalContext": "把检查清单补回给模型",
            },
            "systemMessage": "已补上",
            "continue": False,
        }, "", ""
    if handler == "sessionstart_compact":
        return 0, None, "", REINJECT_TEXT
    return 0, None, "", ""


@dataclass(frozen=True)
class Record:
    name: str
    kind: str
    handler: str
    matcher: str
    if_set: int
    hook_fired: int
    compacted: int
    request_failed: int
    continued: int
    summary_has_stdout: int
    truncated: int
    model_context_reinjected: int
    saw_summary: int
    instructions: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"kind={self.kind}",
                f"handler={self.handler}",
                f"matcher={self.matcher}",
                f"if_set={self.if_set}",
                f"hook_fired={self.hook_fired}",
                f"compacted={self.compacted}",
                f"request_failed={self.request_failed}",
                f"continued={self.continued}",
                f"summary_has_stdout={self.summary_has_stdout}",
                f"truncated={self.truncated}",
                f"model_context_reinjected={self.model_context_reinjected}",
                f"saw_summary={self.saw_summary}",
            ]
        )


def settle(
    name: str,
    kind: str,
    handler: str,
    matcher: str = "",
    if_set: bool = False,
    long_stdout: bool = False,
) -> Record:
    """一只处理器挂在这一次压缩上。hook 没跑起来时，压缩照常发生。"""
    if kind not in KINDS:
        raise SystemExit(f"unknown kind {kind}")
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    label = matcher_label(matcher)
    flag = 1 if if_set else 0
    ran = (not if_set) and handler != "none" and matcher_hits(matcher, match_target(handler, kind))
    code, payload, _stderr, stdout = handler_output(handler, long_stdout)
    base = dict(
        name=name,
        kind=kind,
        handler=handler,
        matcher=label,
        if_set=flag,
        instructions="",
    )
    if handler in PRE_HANDLERS and ran and blocks(code, payload):
        compacted, request_failed, continued = outcome(kind, True)
        return Record(
            hook_fired=1,
            compacted=compacted,
            request_failed=request_failed,
            continued=continued,
            summary_has_stdout=0,
            truncated=0,
            model_context_reinjected=0,
            saw_summary=0,
            **base,
        )
    compacted, request_failed, continued = outcome(kind, False)
    if handler == "pre_stdout_instructions" and ran:
        text, truncated = clip(stdout)
        kept = stdout[:CAP]
        return Record(
            hook_fired=1,
            compacted=compacted,
            request_failed=request_failed,
            continued=continued,
            summary_has_stdout=1 if kept and kept in text else 0,
            truncated=truncated,
            model_context_reinjected=0,
            saw_summary=0,
            instructions=text,
            **{key: value for key, value in base.items() if key != "instructions"},
        )
    if handler == "post_only" and ran:
        return Record(
            hook_fired=1,
            compacted=compacted,
            request_failed=request_failed,
            continued=continued,
            summary_has_stdout=0,
            truncated=0,
            model_context_reinjected=0,
            saw_summary=1,
            **base,
        )
    if handler == "sessionstart_compact" and ran and stdout.strip():
        return Record(
            hook_fired=1,
            compacted=compacted,
            request_failed=request_failed,
            continued=continued,
            summary_has_stdout=0,
            truncated=0,
            model_context_reinjected=1,
            saw_summary=0,
            instructions=stdout,
            **{key: value for key, value in base.items() if key != "instructions"},
        )
    return Record(
        hook_fired=1 if ran else 0,
        compacted=compacted,
        request_failed=request_failed,
        continued=continued,
        summary_has_stdout=0,
        truncated=0,
        model_context_reinjected=0,
        saw_summary=0,
        **base,
    )


def printed_records() -> list[Record]:
    rows: list[Record] = []
    handlers = (
        "pre_exit2",
        "pre_block_decision",
        "pre_stdout_instructions",
        "post_only",
        "sessionstart_compact",
        "none",
    )
    for kind in ("manual", "auto_before_limit", "auto_limit_error"):
        for handler in handlers:
            rows.append(settle(f"{kind}_{handler}", kind, handler))
    rows.append(
        settle(
            "manual_stdout_over_cap",
            "manual",
            "pre_stdout_instructions",
            long_stdout=True,
        )
    )
    rows.append(
        settle(
            "auto_before_limit_if_skipped",
            "auto_before_limit",
            "pre_exit2",
            if_set=True,
        )
    )
    rows.append(
        settle(
            "manual_post_if_skipped",
            "manual",
            "post_only",
            if_set=True,
        )
    )
    rows.append(
        settle(
            "manual_narrow_exit2",
            "manual",
            "pre_exit2",
            matcher="manual",
        )
    )
    rows.append(
        settle(
            "auto_before_limit_wrong_matcher",
            "auto_before_limit",
            "pre_exit2",
            matcher="manual",
        )
    )
    rows.append(settle("manual_pre_discarded_fields", "manual", "pre_discarded_fields"))
    return rows


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    for kind in ("manual", "auto_before_limit", "auto_limit_error"):
        for handler in ("pre_exit2", "pre_block_decision"):
            compacted, request_failed, continued = outcome(kind, True)
            expect(
                records[f"{kind}_{handler}"],
                kind=kind,
                handler=handler,
                matcher="empty",
                if_set=0,
                hook_fired=1,
                compacted=compacted,
                request_failed=request_failed,
                continued=continued,
                summary_has_stdout=0,
                truncated=0,
                model_context_reinjected=0,
                saw_summary=0,
                instructions="",
            )
        expect(
            records[f"{kind}_pre_stdout_instructions"],
            compacted=1,
            request_failed=0,
            continued=1,
            hook_fired=1,
            summary_has_stdout=1,
            truncated=0,
            model_context_reinjected=0,
            saw_summary=0,
            instructions=SHORT_INSTRUCTION,
        )
        expect(
            records[f"{kind}_post_only"],
            compacted=1,
            request_failed=0,
            continued=1,
            hook_fired=1,
            summary_has_stdout=0,
            truncated=0,
            model_context_reinjected=0,
            saw_summary=1,
            instructions="",
        )
        expect(
            records[f"{kind}_sessionstart_compact"],
            compacted=1,
            request_failed=0,
            continued=1,
            hook_fired=1,
            summary_has_stdout=0,
            model_context_reinjected=1,
            saw_summary=0,
            instructions=REINJECT_TEXT,
        )
        expect(
            records[f"{kind}_none"],
            compacted=1,
            request_failed=0,
            continued=1,
            hook_fired=0,
            summary_has_stdout=0,
            truncated=0,
            model_context_reinjected=0,
            saw_summary=0,
            instructions="",
        )
        if custom_instructions(kind) is not None and trigger_of(kind) == "auto":
            raise SystemExit("auto custom_instructions was set")
        if trigger_of(kind) == "manual" and custom_instructions(kind) != "保留检查清单":
            raise SystemExit("manual custom_instructions drifted")
        if records[f"{kind}_pre_stdout_instructions"].instructions == custom_instructions(kind):
            raise SystemExit("summary instructions were the /compact custom_instructions")

    over = records["manual_stdout_over_cap"]
    expect(
        over,
        kind="manual",
        handler="pre_stdout_instructions",
        compacted=1,
        request_failed=0,
        continued=1,
        hook_fired=1,
        summary_has_stdout=1,
        truncated=1,
        model_context_reinjected=0,
        saw_summary=0,
    )
    if not over.instructions.startswith("清单") or "TAIL" in over.instructions:
        raise SystemExit("over-cap stdout kept the tail or lost the prefix")
    if not over.instructions.endswith(FIXTURE_MARKER):
        raise SystemExit("over-cap stdout lost the fixture marker")
    if len(over.instructions) != CAP + len(FIXTURE_MARKER):
        raise SystemExit("over-cap cut length drifted")

    expect(
        records["auto_before_limit_if_skipped"],
        handler="pre_exit2",
        if_set=1,
        hook_fired=0,
        compacted=1,
        request_failed=0,
        continued=1,
        model_context_reinjected=0,
    )
    expect(
        records["manual_post_if_skipped"],
        handler="post_only",
        if_set=1,
        hook_fired=0,
        compacted=1,
        saw_summary=0,
        model_context_reinjected=0,
    )
    expect(
        records["manual_narrow_exit2"],
        kind="manual",
        handler="pre_exit2",
        matcher="manual",
        hook_fired=1,
        compacted=0,
        request_failed=0,
        continued=1,
    )
    expect(
        records["auto_before_limit_wrong_matcher"],
        kind="auto_before_limit",
        handler="pre_exit2",
        matcher="manual",
        hook_fired=0,
        compacted=1,
        request_failed=0,
        continued=1,
    )
    expect(
        records["manual_pre_discarded_fields"],
        handler="pre_discarded_fields",
        hook_fired=1,
        compacted=1,
        request_failed=0,
        continued=1,
        summary_has_stdout=0,
        model_context_reinjected=0,
    )

    if records["auto_before_limit_pre_exit2"].compacted != 0 or records["auto_before_limit_pre_exit2"].continued != 1:
        raise SystemExit("before-limit exit 2 did not skip and continue")
    if records["auto_before_limit_pre_block_decision"].compacted != 0:
        raise SystemExit("before-limit decision block compacted")
    if records["manual_pre_exit2"].compacted != 0 or records["manual_pre_exit2"].request_failed != 0:
        raise SystemExit("manual exit 2 failed the request or compacted")
    if records["manual_pre_block_decision"].compacted != 0 or records["manual_pre_block_decision"].continued != 1:
        raise SystemExit("manual decision block did not skip")
    recovery_exit = records["auto_limit_error_pre_exit2"]
    recovery_block = records["auto_limit_error_pre_block_decision"]
    if recovery_exit.compacted != 0 or recovery_exit.request_failed != 1 or recovery_exit.continued != 0:
        raise SystemExit("recovery exit 2 did not fail the request")
    if recovery_block.compacted != 0 or recovery_block.request_failed != 1:
        raise SystemExit("recovery decision block did not fail the request")
    if records["manual_post_only"].model_context_reinjected != 0 or records["manual_post_only"].saw_summary != 1:
        raise SystemExit("PostCompact reinjected context or missed the summary")
    if records["manual_sessionstart_compact"].model_context_reinjected != 1:
        raise SystemExit("SessionStart compact did not reinject")
    if records["manual_none"].summary_has_stdout != 0 or records["manual_none"].model_context_reinjected != 0:
        raise SystemExit("silence became instructions or reinjection")

    exit_code, exit_payload, exit_stderr, exit_stdout = handler_output("pre_exit2")
    if exit_code != 2 or exit_payload is not None or not exit_stderr or exit_stdout:
        raise SystemExit("exit 2 fixture drifted")
    if not blocks(exit_code, exit_payload):
        raise SystemExit("exit 2 did not block")
    if outcome("auto_before_limit", True) != (0, 0, 1):
        raise SystemExit("before-limit block outcome drifted")
    if outcome("manual", True) != (0, 0, 1):
        raise SystemExit("manual block outcome drifted")
    if outcome("auto_limit_error", True) != (0, 1, 0):
        raise SystemExit("recovery block outcome drifted")

    block_code, block_payload, block_stderr, block_stdout = handler_output("pre_block_decision")
    if block_code != 0 or block_stderr or block_stdout or not isinstance(block_payload, dict):
        raise SystemExit("block JSON fixture did not exit 0")
    if block_payload.get("decision") != "block" or not block_payload.get("reason"):
        raise SystemExit("block JSON fixture lost decision or reason")
    if not block_payload.get("systemMessage") or block_payload.get("continue") is not False:
        raise SystemExit("block JSON fixture lost discarded fields")
    if "hookSpecificOutput" in block_payload:
        raise SystemExit("block JSON fixture hid decision inside hookSpecificOutput")
    if not blocks(block_code, block_payload):
        raise SystemExit("decision block did not block")

    dropped_code, dropped_payload, dropped_stderr, dropped_stdout = handler_output("pre_discarded_fields")
    if dropped_code != 0 or dropped_stderr or dropped_stdout or not isinstance(dropped_payload, dict):
        raise SystemExit("discarded-fields fixture drifted")
    if "decision" in dropped_payload:
        raise SystemExit("discarded-fields fixture set decision")
    if blocks(dropped_code, dropped_payload):
        raise SystemExit("continue or systemMessage blocked compaction")

    post_code, post_payload, post_stderr, post_stdout = handler_output("post_only")
    if post_code != 0 or post_stderr or post_stdout or not isinstance(post_payload, dict):
        raise SystemExit("post fixture drifted")
    extra = post_payload.get("hookSpecificOutput", {}).get("additionalContext")
    if not extra:
        raise SystemExit("post fixture lost additionalContext")
    if plain_stdout_destination("PostCompact") != "debug_log":
        raise SystemExit("PostCompact stdout was treated as model context")
    if plain_stdout_destination("PreCompact") != "summary_instructions":
        raise SystemExit("PreCompact stdout was not summary instructions")
    if plain_stdout_destination("SessionStart") != "model_context":
        raise SystemExit("SessionStart stdout was not model context")
    if blocks(post_code, post_payload):
        raise SystemExit("PostCompact JSON blocked compaction")

    start_code, start_payload, start_stderr, start_stdout = handler_output("sessionstart_compact")
    if (start_code, start_payload, start_stderr, start_stdout) != (0, None, "", REINJECT_TEXT):
        raise SystemExit("sessionstart fixture drifted")

    none_code, none_payload, none_stderr, none_stdout = handler_output("none")
    if (none_code, none_payload, none_stderr, none_stdout) != (0, None, "", ""):
        raise SystemExit("none fixture drifted")
    if blocks(none_code, none_payload):
        raise SystemExit("silence became a block")

    exact, exact_flag = clip("a" * CAP)
    if exact != "a" * CAP or exact_flag != 0:
        raise SystemExit("cap boundary truncated a 10000-character stdout")
    longer, longer_flag = clip("a" * (CAP + 1))
    if longer_flag != 1 or not longer.startswith("a" * CAP) or not longer.endswith(FIXTURE_MARKER):
        raise SystemExit("cap boundary kept an 10001-character stdout whole")

    if custom_instructions("auto_before_limit") is not None or custom_instructions("auto_limit_error") is not None:
        raise SystemExit("auto custom_instructions was not null")

    try:
        settle("bad", "manual", "matcher_opus")
    except SystemExit as exc:
        if "unknown handler" not in str(exc):
            raise
    else:
        raise SystemExit("unknown handler was accepted")

    try:
        trigger_of("server_managed")
    except SystemExit as exc:
        if "unknown kind" not in str(exc):
            raise
    else:
        raise SystemExit("unknown kind was accepted")


def main() -> None:
    rows = printed_records()
    records = {row.name: row for row in rows}
    if len(records) != len(rows):
        raise SystemExit("duplicate case name")
    check(records)
    for row in rows:
        print(records[row.name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
