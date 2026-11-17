#!/usr/bin/env python3
"""伪控制环：SessionEnd 已经在结束，exit 2 也留不住。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
这不是 settings 里的 hook，也不是一次真实的会话退出。
时序和取舍按 Hooks reference、hooks-guide、Agent SDK hooks 的句子在本地走一遍。

夹具不模拟 JavaScript 正则，不算「async 能不能盖过 1.5 秒预算」。
插件 hook 上的 timeout 只记「不抬预算」。它自己能不能跑过共享预算，页上没写，记成 unspecified。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# SessionEnd 专项例子。只改 reason，不补例子里没有的字段。
EXAMPLE_SESSION_ID = "abc123"
EXAMPLE_TRANSCRIPT = (
    "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl"
)
EXAMPLE_CWD = "/Users/..."

LIVE_REASONS = frozenset(
    {"clear", "resume", "logout", "prompt_input_exit", "other"}
)
REMOVED_REASON = "bypass_permissions_disabled"

# 普通 matcher：字母、数字、_、-、空格、,、|。不是 StopFailure 那套更窄字符集。
EXACT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ,|"
)

DEFAULT_MS = 1500
CAP_MS = 60_000
# 文档示例。环境变量的单位是毫秒。
ENV_EXAMPLE_MS = 5000
# command / http / mcp_tool 的普通默认。这只事件不沿用它。
COMMAND_DEFAULT_MS = 600_000

# exit 2 的 stderr 是夹具自己的。页上只写 Shows stderr to user only。
EXIT2_STDERR = "fixture: session already ending"
BLOCK_DECISION = "block"
SYSTEM_MESSAGE = "fixture: please stay"


def classify_matcher(matcher: str | None) -> str:
    if matcher is None or matcher in ("", "*"):
        return "match_all"
    if all(char in EXACT_CHARS for char in matcher):
        return "exact"
    return "regex"


def exact_alternatives(matcher: str) -> list[str]:
    """竖线或逗号分隔，两侧空白可有可无。连字符不切开。"""
    return re.split(r"\s*[|,]\s*", matcher)


def exact_hit(matcher: str | None, reason: str) -> bool:
    if matcher is None or matcher in ("", "*"):
        return True
    return reason in exact_alternatives(matcher)


@dataclass(frozen=True)
class HookSpec:
    name: str
    timeout_s: float | None
    source: str


@dataclass(frozen=True)
class Case:
    name: str
    event: str
    reason: str
    matcher: str | None
    hook_type: str
    handler: str
    hook_if: bool
    hooks: tuple[HookSpec, ...]
    env_ms: int | None
    before_268: bool


@dataclass
class Record:
    name: str
    event: str
    reason: str
    matcher: str
    matcher_path: str
    match_result: str
    hook_type: str
    handler: str
    event_fired: int
    handler_ran: int
    blocks_termination: int
    json_discarded: int
    stderr_to_user: int
    turn_continued: int
    decision_honored: int
    system_message_kept: int
    reason_sent: int
    prompt_supported: int
    agent_supported: int
    if_blocked: int
    budget_ms: str
    unset_hook_ms: str
    own_hook_ms: str
    plugin_raises_budget: str
    plugin_wait_ms: str
    cap_applied: int
    rules: str
    debug_duration: str
    waits_for_server: str
    rejected_600: int
    payload: dict | None

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"event={self.event}",
                f"reason={self.reason}",
                f"matcher={self.matcher}",
                f"matcher_path={self.matcher_path}",
                f"match_result={self.match_result}",
                f"hook_type={self.hook_type}",
                f"handler={self.handler}",
                f"event_fired={self.event_fired}",
                f"handler_ran={self.handler_ran}",
                f"blocks_termination={self.blocks_termination}",
                f"json_discarded={self.json_discarded}",
                f"stderr_to_user={self.stderr_to_user}",
                f"turn_continued={self.turn_continued}",
                f"decision_honored={self.decision_honored}",
                f"system_message_kept={self.system_message_kept}",
                f"reason_sent={self.reason_sent}",
                f"prompt_supported={self.prompt_supported}",
                f"agent_supported={self.agent_supported}",
                f"if_blocked={self.if_blocked}",
                f"budget_ms={self.budget_ms}",
                f"unset_hook_ms={self.unset_hook_ms}",
                f"own_hook_ms={self.own_hook_ms}",
                f"plugin_raises_budget={self.plugin_raises_budget}",
                f"plugin_wait_ms={self.plugin_wait_ms}",
                f"cap_applied={self.cap_applied}",
                f"rules={self.rules}",
                f"debug_duration={self.debug_duration}",
                f"waits_for_server={self.waits_for_server}",
                f"rejected_600={self.rejected_600}",
            ]
        )


def sessionend_payload(reason: str) -> dict:
    return {
        "session_id": EXAMPLE_SESSION_ID,
        "transcript_path": EXAMPLE_TRANSCRIPT,
        "cwd": EXAMPLE_CWD,
        "hook_event_name": "SessionEnd",
        "reason": reason,
    }


def supported_type(hook_type: str) -> bool:
    return hook_type in {"command", "http", "mcp_tool"}


def resolve_budget(
    hooks: tuple[HookSpec, ...], env_ms: int | None, before_268: bool
) -> dict:
    settings_owns = [
        int(hook.timeout_s * 1000)
        for hook in hooks
        if hook.source == "settings" and hook.timeout_s is not None
    ]
    plugin_owns = [
        int(hook.timeout_s * 1000)
        for hook in hooks
        if hook.source == "plugin" and hook.timeout_s is not None
    ]
    if env_ms is not None:
        budget = env_ms
        cap_applied = 0
    elif settings_owns:
        raw = max(settings_owns)
        budget = min(raw, CAP_MS)
        cap_applied = int(raw > CAP_MS)
    else:
        budget = DEFAULT_MS
        cap_applied = 0

    unset_values: list[int] = []
    own_values: list[int] = []
    for hook in hooks:
        if hook.source != "settings":
            continue
        if hook.timeout_s is None:
            if env_ms is not None and not before_268:
                unset_values.append(env_ms)
            else:
                unset_values.append(DEFAULT_MS)
        else:
            own_values.append(min(int(hook.timeout_s * 1000), budget))

    plugin_raises = 0
    if plugin_owns and not settings_owns and env_ms is None:
        plugin_wait = "unspecified"
    elif plugin_owns:
        plugin_wait = "unspecified"
    else:
        plugin_wait = "na"

    return {
        "budget_ms": budget,
        "unset_hook_ms": unset_values[0] if unset_values else "na",
        "own_hook_ms": own_values[0] if own_values else "na",
        "plugin_raises_budget": plugin_raises,
        "plugin_wait_ms": plugin_wait,
        "cap_applied": cap_applied,
    }


def display_matcher(matcher: str | None) -> str:
    if matcher is None:
        return "omitted"
    if matcher == "":
        return "empty"
    return matcher


def settle(case: Case) -> Record:
    reason_sent = int(case.reason in LIVE_REASONS)
    event_fired = int(case.event == "SessionEnd" and reason_sent == 1)
    path = classify_matcher(case.matcher) if case.event == "SessionEnd" else "na"
    if case.event != "SessionEnd":
        match_result = "na"
    elif not reason_sent:
        match_result = "not_sent"
    elif path == "regex":
        match_result = "not_simulated"
    elif exact_hit(case.matcher, case.reason):
        match_result = "hit"
    else:
        match_result = "miss"

    prompt_supported = 0 if case.event == "SessionEnd" else (1 if case.hook_type == "prompt" else 0)
    agent_supported = 0
    if_blocked = int(case.hook_if and case.event == "SessionEnd")
    type_ok = supported_type(case.hook_type) if case.event == "SessionEnd" else case.hook_type == "command"

    handler_ran = int(
        event_fired == 1
        and match_result == "hit"
        and type_ok
        and not if_blocked
    )
    if case.event == "Stop" and case.hook_type in {"command", "mcp_tool"} and not case.hook_if:
        handler_ran = 1

    blocks_termination = 0
    json_discarded = 0
    stderr_to_user = 0
    turn_continued = 0
    decision_honored = 0
    system_message_kept = 0

    if case.event == "SessionEnd" and handler_ran:
        if case.handler == "exit2":
            stderr_to_user = 1
        elif case.handler in {"block", "system_message"}:
            json_discarded = 1
    if case.event == "Stop" and handler_ran and case.handler in {"exit2", "block"}:
        turn_continued = 1
        decision_honored = int(case.handler == "block")

    if case.event == "SessionEnd":
        money = resolve_budget(case.hooks, case.env_ms, case.before_268)
        rules = "before_2.1.268" if case.before_268 else "current"
        debug_duration = "absent" if case.hook_type == "command" and handler_ran else "na"
        waits = "0" if case.hook_type == "mcp_tool" else "na"
        rejected_600 = int(money["budget_ms"] != COMMAND_DEFAULT_MS)
        payload = sessionend_payload(case.reason) if reason_sent else None
    else:
        money = {
            "budget_ms": "na",
            "unset_hook_ms": "na",
            "own_hook_ms": "na",
            "plugin_raises_budget": "na",
            "plugin_wait_ms": "na",
            "cap_applied": 0,
        }
        rules = "na"
        debug_duration = "present" if case.hook_type == "command" and handler_ran else "na"
        waits = "1" if case.hook_type == "mcp_tool" else "na"
        rejected_600 = 0
        payload = None

    return Record(
        name=case.name,
        event=case.event,
        reason=case.reason if case.event == "SessionEnd" else "na",
        matcher=display_matcher(case.matcher) if case.event == "SessionEnd" else "na",
        matcher_path=path,
        match_result=match_result,
        hook_type=case.hook_type,
        handler=case.handler,
        event_fired=event_fired,
        handler_ran=handler_ran,
        blocks_termination=blocks_termination,
        json_discarded=json_discarded,
        stderr_to_user=stderr_to_user,
        turn_continued=turn_continued,
        decision_honored=decision_honored,
        system_message_kept=system_message_kept,
        reason_sent=reason_sent if case.event == "SessionEnd" else 0,
        prompt_supported=0 if case.event == "SessionEnd" else prompt_supported,
        agent_supported=agent_supported,
        if_blocked=if_blocked,
        budget_ms=str(money["budget_ms"]),
        unset_hook_ms=str(money["unset_hook_ms"]),
        own_hook_ms=str(money["own_hook_ms"]),
        plugin_raises_budget=str(money["plugin_raises_budget"]),
        plugin_wait_ms=str(money["plugin_wait_ms"]),
        cap_applied=int(money["cap_applied"]),
        rules=rules,
        debug_duration=debug_duration,
        waits_for_server=waits,
        rejected_600=rejected_600,
        payload=payload,
    )


def hook(name: str, timeout_s: float | None, source: str = "settings") -> HookSpec:
    return HookSpec(name=name, timeout_s=timeout_s, source=source)


DEFAULT_HOOKS = (hook("cleanup", None),)


def case(
    name: str,
    *,
    event: str = "SessionEnd",
    reason: str = "other",
    matcher: str | None = None,
    hook_type: str = "command",
    handler: str = "cleanup",
    hook_if: bool = False,
    hooks: tuple[HookSpec, ...] = DEFAULT_HOOKS,
    env_ms: int | None = None,
    before_268: bool = False,
) -> Case:
    return Case(
        name=name,
        event=event,
        reason=reason,
        matcher=matcher,
        hook_type=hook_type,
        handler=handler,
        hook_if=hook_if,
        hooks=hooks,
        env_ms=env_ms,
        before_268=before_268,
    )


def cases() -> list[Case]:
    per_hook = (
        hook("long", 5),
        hook("unset", None),
    )
    capped = (hook("too_long", 90),)
    plugin_only = (hook("plugin", 10, "plugin"),)
    settings_and_plugin = (
        hook("settings", 5),
        hook("plugin", 30, "plugin"),
    )
    env_hooks = (
        hook("own", 2),
        hook("unset", None),
    )
    env_old = (hook("unset", None),)
    return [
        case("clear_hit", reason="clear", matcher="clear"),
        case("clear_miss_other", reason="other", matcher="clear"),
        case("resume_hit", reason="resume", matcher="resume"),
        case("logout_hit", reason="logout", matcher="logout"),
        case("prompt_input_exit_hit", reason="prompt_input_exit", matcher="prompt_input_exit"),
        case("pipe_hit", reason="resume", matcher="clear|resume"),
        case("comma_hit", reason="clear", matcher="clear, resume"),
        case("hyphen_not_separator", reason="clear", matcher="clear-resume"),
        case("regex_not_simulated", reason="clear", matcher="^clear$"),
        case("match_all_other", reason="other", matcher=None),
        case("removed_not_sent", reason=REMOVED_REASON, matcher=REMOVED_REASON),
        case("removed_matcher_miss", reason="other", matcher=REMOVED_REASON),
        case("exit2_shows_stderr", reason="other", matcher=None, handler="exit2"),
        case("block_discarded", reason="other", matcher=None, handler="block"),
        case("system_message_discarded", reason="other", matcher=None, handler="system_message"),
        case("stop_exit2", event="Stop", handler="exit2", hook_type="command"),
        case("stop_block", event="Stop", handler="block", hook_type="command"),
        case("budget_default", hooks=DEFAULT_HOOKS),
        case("budget_per_hook", hooks=per_hook),
        case("budget_cap_60", hooks=capped),
        case("plugin_no_raise", hooks=plugin_only),
        case("settings_not_plugin", hooks=settings_and_plugin),
        case("env_current", hooks=env_hooks, env_ms=ENV_EXAMPLE_MS),
        case("env_before_268", hooks=env_old, env_ms=ENV_EXAMPLE_MS, before_268=True),
        case("prompt_refused", hook_type="prompt", handler="prompt"),
        case("agent_refused", hook_type="agent", handler="agent"),
        case("if_never_runs", reason="clear", matcher="clear", hook_if=True),
        case("http_allowed", hook_type="http", handler="cleanup"),
        case("mcp_no_wait", hook_type="mcp_tool", handler="cleanup"),
        case("stop_mcp_waits", event="Stop", hook_type="mcp_tool", handler="cleanup"),
    ]


def expect(row: Record, **wanted: object) -> None:
    for key, value in wanted.items():
        got = getattr(row, key)
        if got != value:
            raise SystemExit(f"{row.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["clear_hit"],
        match_result="hit",
        matcher_path="exact",
        handler_ran=1,
        blocks_termination=0,
        event_fired=1,
        reason_sent=1,
        budget_ms="1500",
        rejected_600=1,
    )
    expect(
        records["clear_miss_other"],
        reason="other",
        match_result="miss",
        handler_ran=0,
        event_fired=1,
        blocks_termination=0,
    )
    expect(records["resume_hit"], match_result="hit", handler_ran=1, reason="resume")
    expect(records["logout_hit"], match_result="hit", handler_ran=1, reason="logout")
    expect(
        records["prompt_input_exit_hit"],
        match_result="hit",
        handler_ran=1,
        reason="prompt_input_exit",
        matcher_path="exact",
    )
    expect(
        records["pipe_hit"],
        matcher="clear|resume",
        matcher_path="exact",
        match_result="hit",
        handler_ran=1,
        blocks_termination=0,
    )
    expect(
        records["comma_hit"],
        matcher="clear, resume",
        matcher_path="exact",
        match_result="hit",
        handler_ran=1,
    )
    expect(
        records["hyphen_not_separator"],
        matcher="clear-resume",
        matcher_path="exact",
        match_result="miss",
        handler_ran=0,
    )
    expect(
        records["regex_not_simulated"],
        matcher_path="regex",
        match_result="not_simulated",
        handler_ran=0,
    )
    expect(
        records["match_all_other"],
        matcher="omitted",
        matcher_path="match_all",
        match_result="hit",
        handler_ran=1,
        reason="other",
    )
    expect(
        records["removed_not_sent"],
        reason=REMOVED_REASON,
        reason_sent=0,
        event_fired=0,
        match_result="not_sent",
        handler_ran=0,
        blocks_termination=0,
    )
    expect(
        records["removed_matcher_miss"],
        matcher=REMOVED_REASON,
        reason="other",
        match_result="miss",
        handler_ran=0,
        reason_sent=1,
    )
    expect(
        records["exit2_shows_stderr"],
        handler="exit2",
        handler_ran=1,
        blocks_termination=0,
        stderr_to_user=1,
        json_discarded=0,
        turn_continued=0,
        decision_honored=0,
    )
    expect(
        records["block_discarded"],
        handler="block",
        json_discarded=1,
        blocks_termination=0,
        decision_honored=0,
        turn_continued=0,
        stderr_to_user=0,
    )
    expect(
        records["system_message_discarded"],
        json_discarded=1,
        system_message_kept=0,
        blocks_termination=0,
        turn_continued=0,
    )
    expect(
        records["stop_exit2"],
        event="Stop",
        turn_continued=1,
        blocks_termination=0,
        handler_ran=1,
        event_fired=0,
        debug_duration="present",
    )
    expect(
        records["stop_block"],
        event="Stop",
        turn_continued=1,
        decision_honored=1,
        blocks_termination=0,
    )
    expect(
        records["budget_default"],
        budget_ms="1500",
        unset_hook_ms="1500",
        own_hook_ms="na",
        cap_applied=0,
        rules="current",
        rejected_600=1,
    )
    expect(
        records["budget_per_hook"],
        budget_ms="5000",
        own_hook_ms="5000",
        unset_hook_ms="1500",
        plugin_raises_budget="0",
        cap_applied=0,
    )
    expect(
        records["budget_cap_60"],
        budget_ms="60000",
        own_hook_ms="60000",
        cap_applied=1,
        rules="current",
    )
    expect(
        records["plugin_no_raise"],
        budget_ms="1500",
        plugin_raises_budget="0",
        plugin_wait_ms="unspecified",
        unset_hook_ms="na",
    )
    expect(
        records["settings_not_plugin"],
        budget_ms="5000",
        own_hook_ms="5000",
        plugin_raises_budget="0",
        plugin_wait_ms="unspecified",
    )
    expect(
        records["env_current"],
        budget_ms="5000",
        unset_hook_ms="5000",
        own_hook_ms="2000",
        rules="current",
        cap_applied=0,
    )
    expect(
        records["env_before_268"],
        budget_ms="5000",
        unset_hook_ms="1500",
        rules="before_2.1.268",
        own_hook_ms="na",
    )
    expect(
        records["prompt_refused"],
        hook_type="prompt",
        prompt_supported=0,
        handler_ran=0,
        event_fired=1,
        blocks_termination=0,
    )
    expect(
        records["agent_refused"],
        hook_type="agent",
        agent_supported=0,
        handler_ran=0,
    )
    expect(
        records["if_never_runs"],
        if_blocked=1,
        handler_ran=0,
        match_result="hit",
        event_fired=1,
    )
    expect(
        records["http_allowed"],
        hook_type="http",
        handler_ran=1,
        blocks_termination=0,
        budget_ms="1500",
    )
    expect(
        records["mcp_no_wait"],
        hook_type="mcp_tool",
        handler_ran=1,
        waits_for_server="0",
        blocks_termination=0,
        debug_duration="na",
    )
    expect(
        records["stop_mcp_waits"],
        event="Stop",
        hook_type="mcp_tool",
        waits_for_server="1",
        turn_continued=0,
        event_fired=0,
        blocks_termination=0,
    )

    for row in records.values():
        if row.event == "SessionEnd" and row.blocks_termination:
            raise SystemExit(f"{row.name} blocked termination")
        if row.event == "SessionEnd" and row.turn_continued:
            raise SystemExit(f"{row.name} continued a turn from SessionEnd")
        if row.event == "SessionEnd" and row.system_message_kept:
            raise SystemExit(f"{row.name} kept systemMessage")
        if row.reason_sent and row.reason not in LIVE_REASONS:
            raise SystemExit(f"{row.name} sent a removed reason")
        if row.reason == REMOVED_REASON and (row.reason_sent or row.event_fired or row.handler_ran):
            raise SystemExit(f"{row.name} treated the removed reason as live")
        if (
            row.event == "SessionEnd"
            and row.hook_type == "command"
            and row.handler_ran
            and row.debug_duration != "absent"
        ):
            raise SystemExit(f"{row.name} invented a SessionEnd duration")
        if row.event == "SessionEnd" and row.budget_ms == str(COMMAND_DEFAULT_MS):
            raise SystemExit(f"{row.name} copied the 600s command default")
        if row.plugin_raises_budget not in {"0", "na"}:
            raise SystemExit(f"{row.name} let a plugin hook raise the budget")
        payload = row.payload
        if row.event_fired:
            if not isinstance(payload, dict):
                raise SystemExit(f"{row.name} missing SessionEnd payload")
            if set(payload) != {
                "session_id",
                "transcript_path",
                "cwd",
                "hook_event_name",
                "reason",
            }:
                raise SystemExit(f"{row.name} payload grew fields")
            if payload["hook_event_name"] != "SessionEnd":
                raise SystemExit("hook_event_name drifted")
            if payload["session_id"] != EXAMPLE_SESSION_ID:
                raise SystemExit("session_id drifted")
            if payload["transcript_path"] != EXAMPLE_TRANSCRIPT:
                raise SystemExit("transcript_path drifted")
            if payload["cwd"] != EXAMPLE_CWD:
                raise SystemExit("cwd drifted")
            if payload["reason"] != row.reason:
                raise SystemExit("reason drifted")
        if row.event == "Stop" and row.payload is not None:
            raise SystemExit("Stop contrast grew a SessionEnd payload")

    if classify_matcher("clear, resume") != "exact":
        raise SystemExit("comma matcher left the exact path")
    if classify_matcher("clear-resume") != "exact":
        raise SystemExit("hyphen matcher left the exact path")
    if classify_matcher("^clear$") != "regex":
        raise SystemExit("anchored matcher stayed on the exact path")
    if not exact_hit("clear|resume", "resume") or not exact_hit("clear, resume", "clear"):
        raise SystemExit("exact alternatives drifted")
    if exact_hit("clear-resume", "clear") or exact_hit("clear", "other"):
        raise SystemExit("separator rules drifted")
    if BLOCK_DECISION != "block" or not EXIT2_STDERR or not SYSTEM_MESSAGE:
        raise SystemExit("discarded output fixtures disappeared")


def main() -> None:
    rows = [settle(item) for item in cases()]
    records = {row.name: row for row in rows}
    if len(records) != len(rows):
        raise SystemExit("duplicate case name")
    check(records)
    for row in rows:
        print(row.line())
    print("result=pass")


if __name__ == "__main__":
    main()
