#!/usr/bin/env python3
"""本地夹具：MessageDisplay 只换屏幕上的字，记录和模型视图仍是原文。

不调用 API，不读真实密钥，不访问网络，不启动 Claude Code，不依赖 jq，
也不睡眠。假密钥只有 sk-example-not-a-real-key 和 AKIA_EXAMPLE_NOT_REAL。

这不是 settings 里的 hook，也不是 Claude Code 运行时。

输入输出按 2026-11-23 08:26（Asia/Shanghai）打开的 Hooks reference
（hooks.md）里的 MessageDisplay、matcher 表、退出码表、Decision control
红线、handler 的 timeout 字段，以及 hooks-guide 的生命周期表、无 matcher
行和 Limitations 里的 10 秒默认超时，在本地走一遍。

页上没写成可执行结果的格子 simulated=0，不算裁决：
多只钩子同时交 displayContent 时留下谁的、配了 prompt 或 agent 是跳过还是
报错、displayContent 给空字符串算省略还是显示空、超时记在 debug 还是别处、
一条消息出现两批 final 时怎么结算。
"""

from __future__ import annotations

FAILS: list[str] = []

# 官方示例里的 id。message_id 不是 API 的 msg_… id。
TURN_ID = "0c9e6a2f-7d41-4f4e-9a15-3f4f7c2b8d10"
MESSAGE_ID = "5b2a9c8e-1f63-4d8a-b7c4-9e0d2a6f1c3b"
TRANSCRIPT_MSG_ID = "msg_01EXAMPLE_NOT_A_TRANSCRIPT_CORRELATION"

FAKE_KEYS = ("sk-example-not-a-real-key", "AKIA_EXAMPLE_NOT_REAL")

# 以换行结束。交互模式下最后一批 delta 为空，final 为 true。
# 分批方式是夹具自己的切法。页上写批次边界随流式而定，不要指望某种分组。
# 第一批与官方示例相同。markdown 和假密钥分在后面两批，方便单独超时其中一批。
LINE_PLAN = "Here is the plan:\n"
LINE_MARKDOWN = "Use **bold** and `code`.\n"
LINE_SECRET = "Token sk-example-not-a-real-key and AKIA_EXAMPLE_NOT_REAL\n"
FULL_TEXT = LINE_PLAN + LINE_MARKDOWN + LINE_SECRET

INTERACTIVE = [
    {
        "turn_id": TURN_ID,
        "message_id": MESSAGE_ID,
        "index": 0,
        "final": False,
        "delta": LINE_PLAN,
    },
    {
        "turn_id": TURN_ID,
        "message_id": MESSAGE_ID,
        "index": 1,
        "final": False,
        "delta": LINE_MARKDOWN,
    },
    {
        "turn_id": TURN_ID,
        "message_id": MESSAGE_ID,
        "index": 2,
        "final": False,
        "delta": LINE_SECRET,
    },
    {
        "turn_id": TURN_ID,
        "message_id": MESSAGE_ID,
        "index": 3,
        "final": True,
        "delta": "",
    },
]

# 不以换行结束。最后一批可以停在行中间，delta 非空，结束仍看 final。
MIDLINE = [
    {
        "turn_id": TURN_ID,
        "message_id": MESSAGE_ID,
        "index": 0,
        "final": False,
        "delta": "Starts\n",
    },
    {
        "turn_id": TURN_ID,
        "message_id": MESSAGE_ID,
        "index": 1,
        "final": True,
        "delta": "ends mid",
    },
]

PLAIN = [
    {
        "turn_id": TURN_ID,
        "message_id": MESSAGE_ID,
        "index": 0,
        "final": False,
        "delta": "No markers here.\n",
    },
    {
        "turn_id": TURN_ID,
        "message_id": MESSAGE_ID,
        "index": 1,
        "final": True,
        "delta": "",
    },
]

# 今天打开的用途列表。没有 redact API keys / internal hostnames。
USES = (
    "strip markdown for a minimal display",
    "transform the text an Agent SDK application shows its users",
)

# 决策总表后面「能改写内容」的事件。MessageDisplay 不在这份名单里。
REWRITE_CONTENT = (
    "PreToolUse.updatedInput",
    "PermissionRequest.decision.updatedInput",
    "PostToolUse.updatedToolOutput",
)

# command / http / mcp_tool 的一般默认是 600。这只事件降到 10。
# UserPromptSubmit / PreModelSwitch / PostModelSwitch 是 30。
DEFAULT_TIMEOUT = {
    "command_http_mcp": 600,
    "prompt": 30,
    "agent": 60,
    "userpromptsubmit": 30,
    "premodelswitch": 30,
    "postmodelswitch": 30,
    "messagedisplay": 10,
}

TOOL_EVENTS = frozenset(
    {
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "PermissionRequest",
        "PermissionDenied",
    }
)


def expect(name: str, actual: dict, expected: dict) -> None:
    bad = []
    for key, want in expected.items():
        got = actual.get(key, "<missing>")
        if got != want:
            bad.append(f"{key}: got {got!r} want {want!r}")
    if bad:
        FAILS.append(name + " | " + "; ".join(bad))
    shown = " ".join(
        f"{key}={str(actual.get(key, '<missing>')).replace(chr(10), '\\n')}"
        for key in expected
    )
    print(f"case={name} {shown}")


def strip_markdown(delta: str) -> str:
    """对齐官方 jq：先去掉 **，再去掉行内反引号。"""
    return delta.replace("**", "").replace("`", "")


def star_secrets(delta: str) -> str:
    text = delta
    for secret in FAKE_KEYS:
        text = text.replace(secret, "***")
    return text


def hook_json(delta: str, handler: str) -> dict | None:
    """成功路径返回 JSON。fail 表示脚本没打出合法 JSON，例如缺 jq。"""
    if handler == "fail":
        return None
    if handler == "timeout":
        return None
    if handler == "omit":
        return {"hookSpecificOutput": {"hookEventName": "MessageDisplay"}}
    if handler == "strip":
        return {
            "hookSpecificOutput": {
                "hookEventName": "MessageDisplay",
                "displayContent": strip_markdown(delta),
            }
        }
    if handler == "star":
        return {
            "hookSpecificOutput": {
                "hookEventName": "MessageDisplay",
                "displayContent": star_secrets(delta),
            }
        }
    if handler in {"exit2", "noise"}:
        body = {
            "continue": False,
            "systemMessage": "this is discarded",
            "hookSpecificOutput": {"hookEventName": "MessageDisplay"},
        }
        if handler == "exit2":
            body["hookSpecificOutput"]["displayContent"] = "***"
        else:
            body["hookSpecificOutput"]["displayContent"] = strip_markdown(delta)
        return body
    raise ValueError(handler)


def render_batch(delta: str, handler: str, exit_code: int) -> dict:
    """结算一批屏幕。记录始终是原始 delta。消息不会被拦住。"""
    record = delta
    blocked = 0
    continue_applied = 0
    system_message_applied = 0
    slept = 0
    noted_in = ""
    session_notes_failure = 0
    fell_back = 0

    if handler == "timeout":
        return {
            "screen": record,
            "record": record,
            "blocked": blocked,
            "fell_back": 1,
            "reason": "timed_out",
            "slept": slept,
            "display_applied": 0,
            "continue_applied": continue_applied,
            "system_message_applied": system_message_applied,
            "noted_in": noted_in,
            "session_notes_failure": session_notes_failure,
        }

    if handler == "fail":
        return {
            "screen": record,
            "record": record,
            "blocked": blocked,
            "fell_back": 1,
            "reason": "failed",
            "slept": slept,
            "display_applied": 0,
            "continue_applied": continue_applied,
            "system_message_applied": system_message_applied,
            "noted_in": "debug",
            "session_notes_failure": 0,
        }

    payload = hook_json(delta, handler)
    if exit_code == 2:
        # 退出码表：Can block? No。exit 2 时屏幕是原文。
        # continue 与 systemMessage 按专项丢掉，不拿来拦消息。
        return {
            "screen": record,
            "record": record,
            "blocked": blocked,
            "fell_back": 1,
            "reason": "exit_2",
            "slept": slept,
            "display_applied": 0,
            "continue_applied": continue_applied,
            "system_message_applied": system_message_applied,
            "noted_in": noted_in,
            "session_notes_failure": session_notes_failure,
        }

    specific = (payload or {}).get("hookSpecificOutput") or {}
    if "displayContent" not in specific:
        screen = record
        display_applied = 0
    else:
        screen = specific["displayContent"]
        display_applied = 1
    return {
        "screen": screen,
        "record": record,
        "blocked": blocked,
        "fell_back": fell_back,
        "reason": "ok",
        "slept": slept,
        "display_applied": display_applied,
        "continue_applied": continue_applied,
        "system_message_applied": system_message_applied,
        "noted_in": noted_in,
        "session_notes_failure": session_notes_failure,
    }


def play(batches: list[dict], handler: str, exit_code: int = 0, per_batch: list[str] | None = None) -> dict:
    """以 final 收尾。空 delta 追加进去，不清掉已经拼好的屏幕文本。"""
    screens: list[str] = []
    records: list[str] = []
    indexes: list[int] = []
    finals: list[bool] = []
    message_ids: list[str] = []
    reasons: list[str] = []
    ended = 0
    end_signal = ""
    nonempty_delta_used_as_end = 0
    continue_applied = 0
    system_message_applied = 0
    blocked = 0
    slept = 0
    noted_in = ""
    session_notes_failure = 0

    for batch in batches:
        which = per_batch[batch["index"]] if per_batch else handler
        one = render_batch(batch["delta"], which, exit_code)
        screens.append(one["screen"])
        records.append(one["record"])
        indexes.append(batch["index"])
        finals.append(bool(batch["final"]))
        message_ids.append(batch["message_id"])
        reasons.append(one["reason"])
        continue_applied = max(continue_applied, one["continue_applied"])
        system_message_applied = max(system_message_applied, one["system_message_applied"])
        blocked = max(blocked, one["blocked"])
        slept = max(slept, one["slept"])
        if one["noted_in"]:
            noted_in = one["noted_in"]
        session_notes_failure = max(session_notes_failure, one["session_notes_failure"])
        if batch["final"]:
            ended = 1
            end_signal = "final"
            break

    screen = "".join(screens)
    record = "".join(records)
    before_last = "".join(screens[:-1]) if screens else ""
    last_delta = batches[indexes[-1]]["delta"] if indexes else None
    empty_delta_cleared_screen = 0
    if last_delta == "" and screen == "" and before_last != "":
        empty_delta_cleared_screen = 1

    return {
        "screen": screen,
        "record": record,
        "screen_is_record": int(screen == record),
        "indexes": ",".join(str(i) for i in indexes),
        "final_count": sum(1 for item in finals if item),
        "final_is_last": int(bool(finals) and finals[-1] and finals.count(True) == 1),
        "message_id_stable": int(len(set(message_ids)) == 1 and message_ids[0] == MESSAGE_ID),
        "correlates_transcript_msg_id": int(MESSAGE_ID == TRANSCRIPT_MSG_ID),
        "ended_on_final": ended,
        "end_signal": end_signal,
        "nonempty_delta_used_as_end": nonempty_delta_used_as_end,
        "empty_delta_cleared_screen": empty_delta_cleared_screen,
        "screen_kept": int(screen == before_last) if last_delta == "" else 1,
        "blocked": blocked,
        "continue_applied": continue_applied,
        "system_message_applied": system_message_applied,
        "slept": slept,
        "fell_back_indexes": ",".join(str(indexes[i]) for i, reason in enumerate(reasons) if reason != "ok"),
        "noted_in": noted_in or "none",
        "session_notes_failure": session_notes_failure,
        "calls": len(indexes),
        "keys_on_screen": int(any(secret in screen for secret in FAKE_KEYS)),
        "keys_in_record": int(any(secret in record for secret in FAKE_KEYS)),
        "stars_on_screen": int("***" in screen),
        "bold_on_screen": int("**" in screen),
        "bold_in_record": int("**" in record),
        "ticks_on_screen": int("`" in screen),
        "ticks_in_record": int("`" in record),
    }


def noninteractive_call(full: str) -> dict:
    """Agent SDK 与 claude -p：一次调用，index 0，final true，delta 是全文。"""
    batch = {
        "turn_id": TURN_ID,
        "message_id": MESSAGE_ID,
        "index": 0,
        "final": True,
        "delta": full,
    }
    played = play([batch], "omit")
    return {
        "calls": played["calls"],
        "index": batch["index"],
        "final": int(batch["final"]),
        "delta_is_full": int(batch["delta"] == full),
        "record": played["record"],
    }


def matcher_outcome(kind: str, matcher: str | None) -> dict:
    """没有 matcher。写了也会被静默忽略。无文本的纯工具回复不开火。"""
    silently_ignored = 1 if matcher is not None else 0
    if kind == "tool_only":
        fires = 0
    elif kind == "assistant_text":
        fires = 1
    else:
        raise ValueError(kind)
    return {
        "fires": fires,
        "matcher_applied": 0,
        "silently_ignored": silently_ignored,
    }


def outside_text(kind: str, text: str) -> dict:
    """工具结果和用户键入的文字不进钩子输入，渲染保持原文。"""
    if kind == "assistant_text":
        return {"hook_received": 1, "rendered": strip_markdown(text), "unchanged": int(strip_markdown(text) == text)}
    if kind in {"tool_result", "user_typed"}:
        return {"hook_received": 0, "rendered": text, "unchanged": 1}
    raise ValueError(kind)


def if_runs(event: str, has_if: bool) -> int:
    """if 只在工具事件上评估。别的事件写了 if，钩子永不跑。"""
    if has_if and event not in TOOL_EVENTS:
        return 0
    return 1


def main() -> None:
    official = INTERACTIVE[0]
    expect(
        "official_input_example",
        {
            "hook_event_name": "MessageDisplay",
            "index": official["index"],
            "final": official["final"],
            "delta": official["delta"],
            "turn_id": official["turn_id"],
            "message_id": official["message_id"],
        },
        {
            "hook_event_name": "MessageDisplay",
            "index": 0,
            "final": False,
            "delta": "Here is the plan:\n",
            "turn_id": TURN_ID,
            "message_id": MESSAGE_ID,
        },
    )

    stripped = play(INTERACTIVE, "strip")
    expect(
        "interactive_strip",
        stripped,
        {
            "indexes": "0,1,2,3",
            "final_count": 1,
            "final_is_last": 1,
            "message_id_stable": 1,
            "calls": 4,
            "screen_is_record": 0,
            "bold_on_screen": 0,
            "ticks_on_screen": 0,
            "bold_in_record": 1,
            "ticks_in_record": 1,
            "keys_on_screen": 1,
            "keys_in_record": 1,
            "blocked": 0,
            "end_signal": "final",
            "nonempty_delta_used_as_end": 0,
            "empty_delta_cleared_screen": 0,
            "screen_kept": 1,
        },
    )

    starred = play(INTERACTIVE, "star")
    expect(
        "interactive_star",
        starred,
        {
            "screen_is_record": 0,
            "keys_on_screen": 0,
            "keys_in_record": 1,
            "stars_on_screen": 1,
            "bold_on_screen": 1,
            "bold_in_record": 1,
            "blocked": 0,
            "message_id_stable": 1,
            "correlates_transcript_msg_id": 0,
        },
    )

    expect(
        "empty_final_delta",
        {
            "last_delta_empty": int(INTERACTIVE[-1]["delta"] == ""),
            "last_final": int(INTERACTIVE[-1]["final"]),
            "end_signal": stripped["end_signal"],
            "nonempty_delta_used_as_end": stripped["nonempty_delta_used_as_end"],
            "empty_delta_cleared_screen": stripped["empty_delta_cleared_screen"],
            "screen_kept": stripped["screen_kept"],
            "screen_nonempty": int(stripped["screen"] != ""),
        },
        {
            "last_delta_empty": 1,
            "last_final": 1,
            "end_signal": "final",
            "nonempty_delta_used_as_end": 0,
            "empty_delta_cleared_screen": 0,
            "screen_kept": 1,
            "screen_nonempty": 1,
        },
    )

    midline = play(MIDLINE, "strip")
    expect(
        "midline_final",
        {
            "final_count": midline["final_count"],
            "end_signal": midline["end_signal"],
            "screen": midline["screen"],
            "record": midline["record"],
            "last_delta_empty": int(MIDLINE[-1]["delta"] == ""),
        },
        {
            "final_count": 1,
            "end_signal": "final",
            "screen": "Starts\nends mid",
            "record": "Starts\nends mid",
            "last_delta_empty": 0,
        },
    )

    once = noninteractive_call(FULL_TEXT)
    interactive_omit = play(INTERACTIVE, "omit")
    expect(
        "noninteractive_once",
        {
            "calls": once["calls"],
            "index": once["index"],
            "final": once["final"],
            "delta_is_full": once["delta_is_full"],
            "record_matches_interactive": int(once["record"] == interactive_omit["record"] == FULL_TEXT),
        },
        {
            "calls": 1,
            "index": 0,
            "final": 1,
            "delta_is_full": 1,
            "record_matches_interactive": 1,
        },
    )

    once_strip = play(
        [
            {
                "turn_id": TURN_ID,
                "message_id": MESSAGE_ID,
                "index": 0,
                "final": True,
                "delta": FULL_TEXT,
            }
        ],
        "strip",
    )
    expect(
        "delta_totals_match",
        {
            "same_record": int(stripped["record"] == once_strip["record"] == FULL_TEXT),
            "screens_differ_from_record": int(
                stripped["screen"] != stripped["record"] and once_strip["screen"] != once_strip["record"]
            ),
            "strip_screens_match": int(stripped["screen"] == once_strip["screen"]),
        },
        {
            "same_record": 1,
            "screens_differ_from_record": 1,
            "strip_screens_match": 1,
        },
    )

    expect(
        "omit_display_content",
        {
            "screen_is_record": interactive_omit["screen_is_record"],
            "screen_is_full": int(interactive_omit["screen"] == FULL_TEXT),
            "blocked": interactive_omit["blocked"],
        },
        {
            "screen_is_record": 1,
            "screen_is_full": 1,
            "blocked": 0,
        },
    )

    plain = play(PLAIN, "strip")
    expect(
        "plain_batch_unchanged",
        {
            "screen": plain["screen"],
            "record": plain["record"],
            "screen_is_record": plain["screen_is_record"],
            "display_equals_delta": int(plain["screen"] == "No markers here.\n"),
        },
        {
            "screen": "No markers here.\n",
            "record": "No markers here.\n",
            "screen_is_record": 1,
            "display_equals_delta": 1,
        },
    )

    exited = play(INTERACTIVE, "exit2", exit_code=2)
    expect(
        "exit2_no_block",
        {
            "blocked": exited["blocked"],
            "screen_is_record": exited["screen_is_record"],
            "screen_is_full": int(exited["screen"] == FULL_TEXT),
            "record_is_full": int(exited["record"] == FULL_TEXT),
            "continue_applied": exited["continue_applied"],
            "system_message_applied": exited["system_message_applied"],
            "fell_back_indexes": exited["fell_back_indexes"],
            "keys_in_record": exited["keys_in_record"],
        },
        {
            "blocked": 0,
            "screen_is_record": 1,
            "screen_is_full": 1,
            "record_is_full": 1,
            "continue_applied": 0,
            "system_message_applied": 0,
            "fell_back_indexes": "0,1,2,3",
            "keys_in_record": 1,
        },
    )

    noise = play(INTERACTIVE, "noise", exit_code=0)
    expect(
        "discard_continue_and_system_message",
        noise,
        {
            "blocked": 0,
            "continue_applied": 0,
            "system_message_applied": 0,
            "screen_is_record": 0,
            "bold_on_screen": 0,
            "bold_in_record": 1,
            "keys_in_record": 1,
        },
    )

    failed = play(INTERACTIVE, "fail")
    expect(
        "fail_falls_back",
        {
            "screen_is_full": int(failed["screen"] == FULL_TEXT),
            "record_is_full": int(failed["record"] == FULL_TEXT),
            "screen_is_record": failed["screen_is_record"],
            "blocked": failed["blocked"],
            "noted_in": failed["noted_in"],
            "session_notes_failure": failed["session_notes_failure"],
            "fell_back_indexes": failed["fell_back_indexes"],
        },
        {
            "screen_is_full": 1,
            "record_is_full": 1,
            "screen_is_record": 1,
            "blocked": 0,
            "noted_in": "debug",
            "session_notes_failure": 0,
            "fell_back_indexes": "0,1,2,3",
        },
    )

    timed = play(INTERACTIVE, "timeout")
    expect(
        "timeout_falls_back",
        {
            "screen_is_full": int(timed["screen"] == FULL_TEXT),
            "record_is_full": int(timed["record"] == FULL_TEXT),
            "blocked": timed["blocked"],
            "slept": timed["slept"],
            "fell_back_indexes": timed["fell_back_indexes"],
        },
        {
            "screen_is_full": 1,
            "record_is_full": 1,
            "blocked": 0,
            "slept": 0,
            "fell_back_indexes": "0,1,2,3",
        },
    )

    # 第 1 批超时，屏幕留着 **。第 2 批仍把假密钥换成星号。记录两边都是原文。
    partial = play(INTERACTIVE, "star", per_batch=["star", "timeout", "star", "star"])
    expect(
        "partial_timeout",
        {
            "fell_back_indexes": partial["fell_back_indexes"],
            "screen_is_record": partial["screen_is_record"],
            "bold_on_screen": partial["bold_on_screen"],
            "bold_in_record": partial["bold_in_record"],
            "keys_on_screen": partial["keys_on_screen"],
            "keys_in_record": partial["keys_in_record"],
            "stars_on_screen": partial["stars_on_screen"],
            "slept": partial["slept"],
            "record_is_full": int(partial["record"] == FULL_TEXT),
            "blocked": partial["blocked"],
            "markdown_batch_original": int(LINE_MARKDOWN in partial["screen"]),
        },
        {
            "fell_back_indexes": "1",
            "screen_is_record": 0,
            "bold_on_screen": 1,
            "bold_in_record": 1,
            "keys_on_screen": 0,
            "keys_in_record": 1,
            "stars_on_screen": 1,
            "slept": 0,
            "record_is_full": 1,
            "blocked": 0,
            "markdown_batch_original": 1,
        },
    )

    both = [matcher_outcome("assistant_text", "Bash") for _ in range(2)]
    tool_only = matcher_outcome("tool_only", "Bash")
    bare = matcher_outcome("assistant_text", None)
    expect(
        "no_matcher",
        {
            "fires": both[0]["fires"] + both[1]["fires"],
            "matcher_applied": both[0]["matcher_applied"],
            "silently_ignored": both[0]["silently_ignored"],
            "tool_only_fires": tool_only["fires"],
            "bare_fires": bare["fires"],
            "bare_silently_ignored": bare["silently_ignored"],
        },
        {
            "fires": 2,
            "matcher_applied": 0,
            "silently_ignored": 1,
            "tool_only_fires": 0,
            "bare_fires": 1,
            "bare_silently_ignored": 0,
        },
    )

    user_text = "请看 sk-example-not-a-real-key"
    tool_text = "stdout AKIA_EXAMPLE_NOT_REAL"
    user = outside_text("user_typed", user_text)
    tool = outside_text("tool_result", tool_text)
    expect(
        "tool_and_user_unchanged",
        {
            "user_received": user["hook_received"],
            "user_unchanged": user["unchanged"],
            "user_rendered": user["rendered"],
            "tool_received": tool["hook_received"],
            "tool_unchanged": tool["unchanged"],
            "tool_rendered": tool["rendered"],
        },
        {
            "user_received": 0,
            "user_unchanged": 1,
            "user_rendered": user_text,
            "tool_received": 0,
            "tool_unchanged": 1,
            "tool_rendered": tool_text,
        },
    )

    expect(
        "if_never_runs",
        {
            "message_display_with_if": if_runs("MessageDisplay", True),
            "message_display_without_if": if_runs("MessageDisplay", False),
            "pretooluse_with_if": if_runs("PreToolUse", True),
        },
        {
            "message_display_with_if": 0,
            "message_display_without_if": 1,
            "pretooluse_with_if": 1,
        },
    )

    uses_text = " ".join(USES).lower()
    expect(
        "timeouts_and_uses",
        {
            "messagedisplay": DEFAULT_TIMEOUT["messagedisplay"],
            "guide_same": 10,
            "command_http_mcp": DEFAULT_TIMEOUT["command_http_mcp"],
            "userpromptsubmit": DEFAULT_TIMEOUT["userpromptsubmit"],
            "use_count": len(USES),
            "lists_redact_keys": int("redact api keys" in uses_text or "internal hostnames" in uses_text),
            "on_rewrite_list": int("MessageDisplay" in " ".join(REWRITE_CONTENT)),
        },
        {
            "messagedisplay": 10,
            "guide_same": 10,
            "command_http_mcp": 600,
            "userpromptsubmit": 30,
            "use_count": 2,
            "lists_redact_keys": 0,
            "on_rewrite_list": 0,
        },
    )

    expect(
        "unread",
        {
            "parallel_display_merge": "not_stated",
            "prompt_agent_outcome": "not_stated",
            "empty_display_content": "not_stated",
            "timeout_note": "not_stated",
            "two_finals": "not_stated",
            "parallel_simulated": 0,
            "prompt_agent_simulated": 0,
            "empty_display_simulated": 0,
            "timeout_note_simulated": 0,
            "two_finals_simulated": 0,
        },
        {
            "parallel_display_merge": "not_stated",
            "prompt_agent_outcome": "not_stated",
            "empty_display_content": "not_stated",
            "timeout_note": "not_stated",
            "two_finals": "not_stated",
            "parallel_simulated": 0,
            "prompt_agent_simulated": 0,
            "empty_display_simulated": 0,
            "timeout_note_simulated": 0,
            "two_finals_simulated": 0,
        },
    )

    if FAILS:
        for item in FAILS:
            print(f"FAIL {item}")
        print("result=fail")
        raise SystemExit(1)
    print("result=pass")


if __name__ == "__main__":
    main()
