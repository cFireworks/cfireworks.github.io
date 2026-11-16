#!/usr/bin/env python3
"""伪控制环：StopFailure 替掉了 Stop，exit 2 也改不了结局。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
这不是 settings 里的 hook。时序和取舍按 Hooks reference 的句子在本地走一遍。

夹具不模拟八次连拦，也不计算正则匹配。
terminalSequence 只记旗标，不写终端，不响铃。
"""

from __future__ import annotations

from dataclasses import dataclass

ERROR_TYPES = frozenset(
    {
        "rate_limit",
        "overloaded",
        "authentication_failed",
        "oauth_org_not_allowed",
        "account_on_hold",
        "billing_error",
        "invalid_request",
        "model_not_found",
        "server_error",
        "max_output_tokens",
        "cloud_credential_error",
        "unknown",
    }
)

# StopFailure 专项例子。只在 rate_limit 上使用。
RATE_LIMIT_DETAILS = "429 Too Many Requests"
RATE_LIMIT_MESSAGE = "API Error: Rate limit reached"
# Stop 专项例子。装的是模型回复，不是错误原文。
STOP_MESSAGE = "I've completed the refactoring. Here's a summary..."
# Stop 决策节的例子句子。
BLOCK_REASON = "Must be provided when Claude is blocked from stopping"
STOP_CONTEXT = "Please run the test suite before finishing"
# exit 2 的 stderr 是夹具自己的。页上只写它走「为什么要继续」的路径。
EXIT2_STDERR = "测试还没绿"
# 误判理由是夹具自己的。页上没有这句。
WRONG_REASON = "fixture: treated the error string as a model reply"
# 精确匹配字符集：字母、数字、_、|。星号和空字符串在这之前算 match all。
EXACT_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_|")
BEL = "\a"
CSI = "\x1b[31m"
STOP_ONLY_FIELDS = ("stop_hook_active", "background_tasks", "session_crons")


def mistaken_treats_message_as_reply(message: str | None) -> bool:
    """非空就当成模型已经回话。这是要被夹具拒绝的误用。"""
    return bool(message)


def classify_matcher(matcher: str) -> str:
    if matcher in ("", "*"):
        return "match_all"
    if all(char in EXACT_CHARS for char in matcher):
        return "exact"
    return "regex"


def exact_hit(matcher: str, error: str) -> bool:
    if matcher in ("", "*"):
        return True
    return error in matcher.split("|")


def terminal_kept(value: str | None) -> int:
    if value is None:
        return 0
    if value == BEL:
        return 1
    if value == CSI:
        return 0
    raise SystemExit("allowlist parser is not simulated")


@dataclass(frozen=True)
class Case:
    name: str
    ending: str
    error: str | None
    handler: str
    matcher: str
    hook_if: bool
    hook_type: str


@dataclass
class Record:
    name: str
    ending: str
    error: str
    handler: str
    matcher: str
    matcher_path: str
    match_result: str
    hook_type: str
    stop_fired: int
    stop_failure_fired: int
    handler_ran: int
    continued: int
    output_ignored: int
    terminal_sequence_kept: int
    wrong_field_semantics: int
    judged_done: int
    prompt_supported: str
    prompt_refused: int
    if_blocked: int
    context_honored: int
    turn_end: str
    message_role: str
    payload: dict | None

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"ending={self.ending}",
                f"error={self.error}",
                f"handler={self.handler}",
                f"matcher={self.matcher}",
                f"matcher_path={self.matcher_path}",
                f"match_result={self.match_result}",
                f"hook_type={self.hook_type}",
                f"stop_fired={self.stop_fired}",
                f"stop_failure_fired={self.stop_failure_fired}",
                f"handler_ran={self.handler_ran}",
                f"continued={self.continued}",
                f"output_ignored={self.output_ignored}",
                f"terminal_sequence_kept={self.terminal_sequence_kept}",
                f"wrong_field_semantics={self.wrong_field_semantics}",
                f"judged_done={self.judged_done}",
                f"prompt_supported={self.prompt_supported}",
                f"prompt_refused={self.prompt_refused}",
                f"if_blocked={self.if_blocked}",
                f"context_honored={self.context_honored}",
                f"turn_end={self.turn_end}",
                f"message_role={self.message_role}",
            ]
        )


def display_matcher(ending: str, matcher: str) -> str:
    if ending != "api_error" and matcher == "":
        return "na"
    if matcher == "":
        return "empty"
    return matcher


def stop_payload() -> dict:
    return {
        "hook_event_name": "Stop",
        "stop_hook_active": False,
        "last_assistant_message": STOP_MESSAGE,
        "background_tasks": [],
        "session_crons": [],
    }


def failure_payload(error: str) -> dict:
    payload = {"hook_event_name": "StopFailure", "error": error}
    if error == "rate_limit":
        payload["error_details"] = RATE_LIMIT_DETAILS
        payload["last_assistant_message"] = RATE_LIMIT_MESSAGE
    return payload


def cases() -> list[Case]:
    return [
        Case("agent_finished_allow", "agent_finished", None, "none", "", False, "command"),
        Case("agent_finished_exit2", "agent_finished", None, "exit2", "", False, "command"),
        Case("agent_finished_block", "agent_finished", None, "block", "", False, "command"),
        Case("agent_finished_context", "agent_finished", None, "additional_context", "", False, "command"),
        Case("agent_finished_matcher", "agent_finished", None, "exit2", "rate_limit", False, "command"),
        Case("stop_if_never_runs", "agent_finished", None, "exit2", "", True, "command"),
        Case("user_interrupt", "user_interrupt", None, "exit2", "", False, "command"),
        Case("tool_failure_in_loop", "in_loop", None, "exit2", "", False, "command"),
        Case("rate_limit_exit2", "api_error", "rate_limit", "exit2", "rate_limit", False, "command"),
        Case("auth_block", "api_error", "authentication_failed", "block", "authentication_failed", False, "command"),
        Case("rate_limit_context", "api_error", "rate_limit", "additional_context", "", False, "command"),
        Case("rate_limit_bell", "api_error", "rate_limit", "terminal_bel", "", False, "command"),
        Case("rate_limit_block_bell", "api_error", "rate_limit", "block_bel", "", False, "command"),
        Case("rate_limit_csi", "api_error", "rate_limit", "terminal_csi", "", False, "command"),
        Case("rate_limit_wrong_field", "api_error", "rate_limit", "wrong_field", "", False, "command"),
        Case("matcher_miss", "api_error", "authentication_failed", "exit2", "rate_limit", False, "command"),
        Case("matcher_pipe", "api_error", "authentication_failed", "exit2", "rate_limit|authentication_failed", False, "command"),
        Case("matcher_comma", "api_error", "rate_limit", "exit2", "rate_limit,authentication_failed", False, "command"),
        Case("matcher_hyphen", "api_error", "rate_limit", "exit2", "rate-limit", False, "command"),
        Case("prompt_refused", "api_error", "rate_limit", "block", "", False, "prompt"),
        Case("failure_if_never_runs", "api_error", "rate_limit", "exit2", "rate_limit", True, "command"),
    ]


def settle(case: Case) -> Record:
    if case.ending not in {"agent_finished", "user_interrupt", "api_error", "in_loop"}:
        raise SystemExit(f"unknown ending {case.ending}")
    if case.ending == "api_error":
        if case.error not in ERROR_TYPES:
            raise SystemExit(f"unknown error {case.error}")
    elif case.error is not None:
        raise SystemExit("only api_error carries an error value")
    if case.hook_type not in {"command", "prompt"}:
        raise SystemExit("http and mcp_tool transports are not simulated")

    stop_fires = case.ending == "agent_finished"
    failure_fires = case.ending == "api_error"
    if stop_fires == failure_fires and case.ending in {"agent_finished", "api_error"}:
        raise SystemExit("Stop and StopFailure both fired")

    if case.ending == "agent_finished":
        payload: dict | None = stop_payload()
        message_role = "model_reply"
        prompt_supported = "1"
    elif case.ending == "api_error":
        payload = failure_payload(case.error or "")
        message_role = "api_error_text" if "last_assistant_message" in payload else "absent"
        prompt_supported = "0"
    else:
        payload = None
        message_role = "na"
        prompt_supported = "na"

    record = Record(
        name=case.name,
        ending=case.ending,
        error=case.error or "-",
        handler=case.handler,
        matcher=display_matcher(case.ending, case.matcher),
        matcher_path="na",
        match_result="na",
        hook_type=case.hook_type,
        stop_fired=int(stop_fires),
        stop_failure_fired=int(failure_fires),
        handler_ran=0,
        continued=0,
        output_ignored=0,
        terminal_sequence_kept=0,
        wrong_field_semantics=0,
        judged_done=0,
        prompt_supported=prompt_supported,
        prompt_refused=0,
        if_blocked=0,
        context_honored=0,
        turn_end={
            "agent_finished": "normal",
            "user_interrupt": "interrupted",
            "api_error": "api_error",
            "in_loop": "open",
        }[case.ending],
        message_role=message_role,
        payload=payload,
    )

    if not stop_fires and not failure_fires:
        return record

    if case.hook_type == "prompt":
        if not failure_fires:
            raise SystemExit("Stop prompt evaluator is not simulated")
        record.prompt_refused = 1
        return record

    if case.hook_if:
        record.if_blocked = 1
        return record

    if stop_fires:
        if case.matcher != "":
            record.matcher_path = "ignored"
            record.match_result = "ignored"
        apply_stop(record, case.handler)
        return record

    path = classify_matcher(case.matcher)
    record.matcher_path = path
    if path == "regex":
        record.match_result = "not_simulated"
        return record
    hit = exact_hit(case.matcher, case.error or "")
    record.match_result = "hit" if hit else "miss"
    if not hit or case.handler == "none":
        return record
    apply_failure(record, case.handler)
    return record


def apply_stop(record: Record, handler: str) -> None:
    if handler == "none":
        return
    if handler == "exit2":
        record.handler_ran = 1
        record.continued = 1
        record.turn_end = "continued"
        return
    if handler == "block":
        record.handler_ran = 1
        record.continued = 1
        record.turn_end = "continued"
        return
    if handler == "additional_context":
        record.handler_ran = 1
        record.continued = 1
        record.turn_end = "continued"
        record.context_honored = 1
        return
    raise SystemExit(f"handler {handler} is not a Stop gate in this fixture")


def apply_failure(record: Record, handler: str) -> None:
    message = None if record.payload is None else record.payload.get("last_assistant_message")
    sequence = None
    if handler == "exit2":
        pass
    elif handler == "block":
        pass
    elif handler == "additional_context":
        pass
    elif handler == "terminal_bel":
        sequence = BEL
    elif handler == "terminal_csi":
        sequence = CSI
    elif handler == "block_bel":
        sequence = BEL
    elif handler == "wrong_field":
        if not mistaken_treats_message_as_reply(message if isinstance(message, str) else None):
            raise SystemExit("wrong-field case no longer demonstrates the mistake")
        record.wrong_field_semantics = 1
        record.judged_done = 0
    else:
        raise SystemExit(f"unknown StopFailure handler {handler}")
    record.handler_ran = 1
    record.continued = 0
    record.output_ignored = 1
    record.terminal_sequence_kept = terminal_kept(sequence)
    record.context_honored = 0
    record.turn_end = "api_error"


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["agent_finished_allow"],
        ending="agent_finished",
        stop_fired=1,
        stop_failure_fired=0,
        handler_ran=0,
        continued=0,
        output_ignored=0,
        turn_end="normal",
        message_role="model_reply",
        prompt_supported="1",
    )
    expect(
        records["agent_finished_exit2"],
        handler="exit2",
        stop_fired=1,
        stop_failure_fired=0,
        handler_ran=1,
        continued=1,
        output_ignored=0,
        turn_end="continued",
        context_honored=0,
    )
    expect(
        records["agent_finished_block"],
        handler="block",
        continued=1,
        turn_end="continued",
        output_ignored=0,
        stop_failure_fired=0,
    )
    expect(
        records["agent_finished_context"],
        handler="additional_context",
        continued=1,
        context_honored=1,
        turn_end="continued",
        output_ignored=0,
    )
    expect(
        records["agent_finished_matcher"],
        matcher="rate_limit",
        matcher_path="ignored",
        match_result="ignored",
        stop_fired=1,
        handler_ran=1,
        continued=1,
    )
    expect(
        records["stop_if_never_runs"],
        stop_fired=1,
        if_blocked=1,
        handler_ran=0,
        continued=0,
        turn_end="normal",
    )
    expect(
        records["user_interrupt"],
        ending="user_interrupt",
        stop_fired=0,
        stop_failure_fired=0,
        handler_ran=0,
        continued=0,
        turn_end="interrupted",
        payload=None,
    )
    expect(
        records["tool_failure_in_loop"],
        ending="in_loop",
        stop_fired=0,
        stop_failure_fired=0,
        handler_ran=0,
        continued=0,
        turn_end="open",
    )
    expect(
        records["rate_limit_exit2"],
        error="rate_limit",
        matcher="rate_limit",
        matcher_path="exact",
        match_result="hit",
        stop_fired=0,
        stop_failure_fired=1,
        handler_ran=1,
        continued=0,
        output_ignored=1,
        terminal_sequence_kept=0,
        turn_end="api_error",
        message_role="api_error_text",
        prompt_supported="0",
    )
    expect(
        records["auth_block"],
        error="authentication_failed",
        matcher="authentication_failed",
        match_result="hit",
        stop_fired=0,
        stop_failure_fired=1,
        handler_ran=1,
        continued=0,
        output_ignored=1,
        message_role="absent",
    )
    expect(
        records["rate_limit_context"],
        handler="additional_context",
        handler_ran=1,
        continued=0,
        output_ignored=1,
        context_honored=0,
        stop_fired=0,
    )
    expect(
        records["rate_limit_bell"],
        handler="terminal_bel",
        continued=0,
        output_ignored=1,
        terminal_sequence_kept=1,
        turn_end="api_error",
    )
    expect(
        records["rate_limit_block_bell"],
        handler="block_bel",
        continued=0,
        output_ignored=1,
        terminal_sequence_kept=1,
    )
    expect(
        records["rate_limit_csi"],
        handler="terminal_csi",
        continued=0,
        output_ignored=1,
        terminal_sequence_kept=0,
    )
    expect(
        records["rate_limit_wrong_field"],
        handler="wrong_field",
        stop_failure_fired=1,
        stop_fired=0,
        handler_ran=1,
        continued=0,
        output_ignored=1,
        wrong_field_semantics=1,
        judged_done=0,
        message_role="api_error_text",
    )
    expect(
        records["matcher_miss"],
        error="authentication_failed",
        matcher="rate_limit",
        matcher_path="exact",
        match_result="miss",
        stop_failure_fired=1,
        stop_fired=0,
        handler_ran=0,
        continued=0,
        output_ignored=0,
    )
    expect(
        records["matcher_pipe"],
        matcher="rate_limit|authentication_failed",
        matcher_path="exact",
        match_result="hit",
        error="authentication_failed",
        handler_ran=1,
        continued=0,
        output_ignored=1,
        stop_fired=0,
    )
    expect(
        records["matcher_comma"],
        matcher="rate_limit,authentication_failed",
        matcher_path="regex",
        match_result="not_simulated",
        handler_ran=0,
        continued=0,
        output_ignored=0,
        stop_failure_fired=1,
    )
    expect(
        records["matcher_hyphen"],
        matcher="rate-limit",
        matcher_path="regex",
        match_result="not_simulated",
        handler_ran=0,
        stop_failure_fired=1,
    )
    expect(
        records["prompt_refused"],
        hook_type="prompt",
        prompt_supported="0",
        prompt_refused=1,
        handler_ran=0,
        continued=0,
        output_ignored=0,
        stop_failure_fired=1,
        stop_fired=0,
    )
    expect(
        records["failure_if_never_runs"],
        matcher="rate_limit",
        if_blocked=1,
        handler_ran=0,
        continued=0,
        stop_failure_fired=1,
        output_ignored=0,
    )

    if not mistaken_treats_message_as_reply(RATE_LIMIT_MESSAGE):
        raise SystemExit("documented error string no longer trips the mistaken judge")
    if records["rate_limit_wrong_field"].judged_done:
        raise SystemExit("mistaken judge was honored")

    for row in records.values():
        if row.stop_fired and row.stop_failure_fired:
            raise SystemExit(f"{row.name} fired both events")
        if row.continued and not row.stop_fired:
            raise SystemExit(f"{row.name} continued without Stop")
        if row.stop_failure_fired and row.continued:
            raise SystemExit(f"{row.name} continued after StopFailure")
        if row.terminal_sequence_kept and row.continued:
            raise SystemExit(f"{row.name} treated terminalSequence as a continuation")
        if row.ending == "api_error" and row.message_role == "model_reply":
            raise SystemExit(f"{row.name} read the error string as a model reply")
        if row.prompt_refused and row.handler_ran:
            raise SystemExit(f"{row.name} ran a refused prompt evaluator")
        payload = row.payload
        if row.stop_fired:
            if not isinstance(payload, dict):
                raise SystemExit(f"{row.name} missing Stop payload")
            if payload.get("hook_event_name") != "Stop":
                raise SystemExit("Stop payload drifted")
            if payload.get("last_assistant_message") != STOP_MESSAGE:
                raise SystemExit("Stop message drifted from the documented example")
            if any(field not in payload for field in STOP_ONLY_FIELDS):
                raise SystemExit("Stop payload dropped a documented field")
            if "error" in payload or "error_details" in payload:
                raise SystemExit("Stop payload grew StopFailure fields")
        if row.stop_failure_fired:
            if not isinstance(payload, dict):
                raise SystemExit(f"{row.name} missing StopFailure payload")
            if payload.get("hook_event_name") != "StopFailure":
                raise SystemExit("StopFailure payload drifted")
            if payload.get("error") != row.error:
                raise SystemExit("StopFailure error field drifted")
            if any(field in payload for field in STOP_ONLY_FIELDS):
                raise SystemExit("StopFailure payload grew Stop-only fields")
            if row.error == "rate_limit":
                if payload.get("error_details") != RATE_LIMIT_DETAILS:
                    raise SystemExit("rate_limit details drifted")
                if payload.get("last_assistant_message") != RATE_LIMIT_MESSAGE:
                    raise SystemExit("rate_limit message drifted")
            if row.error == "authentication_failed":
                if "error_details" in payload or "last_assistant_message" in payload:
                    raise SystemExit("auth fixture invented optional fields")

    if classify_matcher("rate_limit|overloaded") != "exact":
        raise SystemExit("pipe matcher left the exact path")
    if classify_matcher("rate limit") != "regex" or classify_matcher("rate_limit,overloaded") != "regex":
        raise SystemExit("space or comma stayed on the exact path")
    if exact_hit("rate_limit", "overloaded") or not exact_hit("billing_error|rate_limit", "rate_limit"):
        raise SystemExit("exact alternatives drifted")
    if terminal_kept(BEL) != 1 or terminal_kept(CSI) != 0 or terminal_kept(None) != 0:
        raise SystemExit("terminalSequence fixture drifted")
    try:
        terminal_kept("\x1b]777;notify;title;body\x07")
    except SystemExit as exc:
        if "not simulated" not in str(exc):
            raise
    else:
        raise SystemExit("a general OSC parser was accepted")


def main() -> None:
    rows = [settle(case) for case in cases()]
    records = {row.name: row for row in rows}
    if len(records) != len(rows):
        raise SystemExit("duplicate case name")
    check(records)
    for row in rows:
        print(row.line())
    print("result=pass")


if __name__ == "__main__":
    main()
