#!/usr/bin/env python3
"""本地夹具：Notification 是提醒，不是授权闸。

不调用 API，不访问网络，不启动 Claude Code，不弹系统通知，
不写 /dev/tty，不依赖 jq，也不睡眠。六秒和六十秒在虚拟时钟上相加。

这不是 settings 里的 hook，也不是 Claude Code 运行时。

输入输出按 2026-11-24 08:32（Asia/Shanghai）打开的 Hooks reference
（hooks.md）里的 Notification 专项、matcher 表、退出码表、Decision control
总表、Emit terminal notifications，以及 PermissionRequest 里「大约六秒才跑
permission_prompt」那句，在本地走一遍。hooks-guide 的空 matcher 和
osascript / notify-send 只作对照，夹具不执行它们。

页上没写成可执行结果的格子 simulated=0，不算裁决：
终端里人先答了会不会取消 permission_prompt、preferredNotifChannel 除
notifications_disabled 以外的取值、这个环境变量在终端会话里关不关
permission_prompt、配了 prompt 或 agent 是跳过还是报错、elicitation 的
按键是不是逐次推迟、用量等待结束时 quota_auto_resume_* 具体是哪一条。
"""

from __future__ import annotations

FAILS: list[str] = []

SIX = 6
SIXTY = 60

SESSION = "abc123"
TRANSCRIPT = "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl"
CWD = "/Users/..."
SAMPLE_MESSAGE = "Claude needs your permission"
SAMPLE_TYPE = "permission_prompt"

# matcher 表里的全部类型。空 matcher 会打到每一种。
ALL_TYPES = (
    "permission_prompt",
    "idle_prompt",
    "auth_success",
    "auth_storage_failure",
    "elicitation_dialog",
    "elicitation_url_dialog",
    "elicitation_complete",
    "elicitation_response",
    "agent_needs_input",
    "agent_completed",
    "quota_auto_resume_fired",
    "quota_auto_resume_stale",
    "quota_auto_resume_disabled",
    "plugin_notification",
)

# 精确匹配字符集。星号、空字符串、省略在这之前算 match all。
EXACT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ,|"
)

TOOL_EVENTS = frozenset(
    {
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "PermissionRequest",
        "PermissionDenied",
    }
)

# 今天打开的 changelog 2.1.331 没有 Notification 专条。夹具不给它加新能力。
CHANGELOG_331_NOTIFICATION_ITEM = 0

BEL = "\a"
ALLOWED_OSC = frozenset({"0", "1", "2", "9", "99", "777"})


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


def notification_input(
    notification_type: str,
    message: str,
    title: str | None = None,
) -> dict:
    """官方示例的形状。title 是专项写的可选字段，示例本身没有。"""
    payload = {
        "session_id": SESSION,
        "transcript_path": TRANSCRIPT,
        "cwd": CWD,
        "hook_event_name": "Notification",
        "message": message,
        "notification_type": notification_type,
    }
    if title is not None:
        payload["title"] = title
    return payload


def matcher_hits(matcher: str | None, notification_type: str) -> bool:
    """省略、空字符串、* 打全部类型。字母数字路径做精确或 |/, 列表。"""
    if matcher is None or matcher in ("", "*"):
        return True
    if all(char in EXACT_CHARS for char in matcher):
        parts = [part.strip() for part in matcher.replace(",", "|").split("|")]
        parts = [part for part in parts if part]
        return notification_type in parts
    raise SystemExit("regex matchers are not simulated")


def permission_due(prompt_at: int, kind: str, keys: list[int]) -> int:
    """终端：从权限窗出现起算，之后每次按键把到期时刻推到这次按键加六秒。

    交给 canUseTool 的会话：出现加六秒，按键不参加。
    """
    if kind == "terminal":
        base = prompt_at
        for moment in keys:
            if moment >= prompt_at and moment >= base:
                base = moment
        return base + SIX
    return prompt_at + SIX


def permission_prompt_fires(
    *,
    now: int,
    prompt_at: int,
    kind: str,
    keys: list[int],
    version: tuple[int, int, int],
    sandbox: bool,
    answered_at: int | None,
    disable: bool,
) -> int:
    """permission_prompt 到点才算开火。返回 1 或 0。不睡眠。"""
    if kind == "sdk" and version < (2, 1, 233):
        return 0
    if kind == "sdk" and disable:
        return 0
    if sandbox and kind != "terminal":
        raise SystemExit("sandbox network timing is specified for terminal sessions")
    if sandbox and version < (2, 1, 246):
        return 0
    due = permission_due(prompt_at, kind, keys)
    if now < due:
        return 0
    # 「先答了就不跑」写在交给 canUseTool 的会话。终端不在这句里。
    if kind == "sdk" and answered_at is not None and answered_at < due:
        return 0
    return 1


def permission_request_fires(sandbox: bool) -> int:
    """即将询问时就开火，不等六秒。沙箱命令的网络请求不走这只事件。"""
    return 0 if sandbox else 1


def permission_snapshot(
    *,
    now: int,
    kind: str,
    keys: list[int] | None = None,
    version: tuple[int, int, int] = (2, 1, 331),
    sandbox: bool = False,
    answered_at: int | None = None,
    answered_by: str = "",
    disable: bool = False,
    behind_dialog: bool = False,
) -> dict:
    prompt_at = 0
    fires = permission_prompt_fires(
        now=now,
        prompt_at=prompt_at,
        kind=kind,
        keys=keys or [],
        version=version,
        sandbox=sandbox,
        answered_at=answered_at,
        disable=disable,
    )
    request = permission_request_fires(sandbox)
    return {
        "now": now,
        "permission_prompt": fires,
        "permission_request": request if now >= prompt_at else 0,
        "permission_request_at": prompt_at if request else -1,
        "permission_request_waited": 0,
        "answered_by": answered_by,
        "notification_while_queued": fires if behind_dialog else 0,
        "slept": 0,
    }


def idle_fires(
    *,
    now: int,
    reply_at: int,
    typed_since: bool,
    agent_running: bool,
    in_usage_wait: bool,
    usage_ended_on_its_own: bool,
) -> dict:
    """结束回复约 60 秒，且之后没打字、没有仍在跑的后台 agent，才发 idle_prompt。

    等用量限制重置期间不发。等待自行结束时改记 quota 家族，不挑具体哪一条。
    """
    if in_usage_wait:
        idle = 0
        quota = 0
    elif usage_ended_on_its_own:
        idle = 0
        quota = 1
    elif typed_since or agent_running or now < reply_at + SIXTY:
        idle = 0
        quota = 0
    else:
        idle = 1
        quota = 0
    return {
        "idle_prompt": idle,
        "quota_family": quota,
        "specific": "not_picked",
        "slept": 0,
    }


def auth_type(storage_ok: bool) -> dict:
    """凭据写不进 storage 时，auth_storage_failure 代替 auth_success。"""
    if storage_ok:
        success, failure = 1, 0
    else:
        success, failure = 0, 1
    return {
        "auth_success": success,
        "auth_storage_failure": failure,
        "both": success & failure,
    }


def sequence_allowed(value: str) -> bool:
    """OSC 0/1/2/9/99/777 或裸 BEL。名单外的任何一段都让整个字段无效。"""
    if value == BEL:
        return True
    index = 0
    size = len(value)
    saw = False
    while index < size:
        if not value.startswith("\x1b]", index):
            return False
        index += 2
        bel_at = value.find(BEL, index)
        st_at = value.find("\x1b\\", index)
        if bel_at == -1 and st_at == -1:
            return False
        if st_at != -1 and (bel_at == -1 or st_at < bel_at):
            param = value[index:st_at]
            index = st_at + 2
        else:
            param = value[index:bel_at]
            index = bel_at + 1
        code = param.split(";", 1)[0]
        if code not in ALLOWED_OSC:
            return False
        saw = True
    return saw


def osc777(title: str, body: str) -> str:
    """对照官方 printf '\\033]777;notify;%s;%s\\007'。不写终端。"""
    return f"\x1b]777;notify;{title};{body}{BEL}"


def example_output(message: str | None, title: str = "Claude Code") -> dict:
    """官方示例：message 缺省时用 Needs your attention，再包进 terminalSequence。"""
    body = message if message else "Needs your attention"
    return {"terminalSequence": osc777(title, body)}


def host_can_write(*, interactive: bool, interface_open: bool, dash_p: bool, agent_sdk: bool) -> bool:
    """只在交互会话且界面开着时写。-p 和 Agent SDK 忽略该字段。"""
    if dash_p or agent_sdk:
        return False
    return interactive and interface_open


def settle(
    message: str,
    output: dict | None,
    exit_code: int,
    *,
    async_: bool = False,
    async_rewake: bool = False,
    interactive: bool = True,
    interface_open: bool = True,
    dash_p: bool = False,
    agent_sdk: bool = False,
) -> dict:
    """通知视为已发送、未被修改。continue 和 systemMessage 丢掉。

    terminalSequence 在宿主还能写、钩子不在后台、序列过名单时，记为由宿主发出。
    """
    background = async_ or async_rewake
    writes = host_can_write(
        interactive=interactive,
        interface_open=interface_open,
        dash_p=dash_p,
        agent_sdk=agent_sdk,
    )
    seq = output.get("terminalSequence") if isinstance(output, dict) else None
    emitted = 0
    if writes and not background and isinstance(seq, str) and sequence_allowed(seq):
        emitted = 1
    return {
        "sent": 1,
        "modified": 0,
        "blocked": 0,
        "message": message,
        "exit_code": exit_code,
        "exit_ignored": 1,
        "stderr_ignored": 1,
        "continue_applied": 0,
        "system_message_applied": 0,
        "terminal_emitted": emitted,
        "emitted_by": "host" if emitted else "none",
        "slept": 0,
    }


def if_runs(event: str, has_if: bool) -> int:
    """if 只在工具事件上求值。别的事件写了 if，钩子不跑。"""
    if has_if and event not in TOOL_EVENTS:
        return 0
    return 1


def main() -> None:
    official = notification_input(SAMPLE_TYPE, SAMPLE_MESSAGE)
    titled = notification_input(SAMPLE_TYPE, SAMPLE_MESSAGE, title="Claude Code")
    expect(
        "input_official",
        {
            "event": official["hook_event_name"],
            "has_message": int(official["message"] == SAMPLE_MESSAGE),
            "has_type": int(official["notification_type"] == SAMPLE_TYPE),
            "has_title": int("title" in official),
            "session_id": official["session_id"],
        },
        {
            "event": "Notification",
            "has_message": 1,
            "has_type": 1,
            "has_title": 0,
            "session_id": SESSION,
        },
    )
    expect(
        "input_with_title",
        {
            "has_title": int(titled.get("title") == "Claude Code"),
            "type": titled["notification_type"],
        },
        {"has_title": 1, "type": SAMPLE_TYPE},
    )

    other = [name for name in ALL_TYPES if name != SAMPLE_TYPE]
    expect(
        "matcher_permission_prompt",
        {
            "types": len(ALL_TYPES),
            "hits_permission": int(matcher_hits(SAMPLE_TYPE, SAMPLE_TYPE)),
            "hits_idle": int(matcher_hits(SAMPLE_TYPE, "idle_prompt")),
            "hits_auth": int(matcher_hits(SAMPLE_TYPE, "auth_success")),
            "hits_other": sum(int(matcher_hits(SAMPLE_TYPE, name)) for name in other),
        },
        {
            "types": 14,
            "hits_permission": 1,
            "hits_idle": 0,
            "hits_auth": 0,
            "hits_other": 0,
        },
    )
    expect(
        "matcher_empty",
        {
            "empty": sum(int(matcher_hits("", name)) for name in ALL_TYPES),
            "star": sum(int(matcher_hits("*", name)) for name in ALL_TYPES),
            "omitted": sum(int(matcher_hits(None, name)) for name in ALL_TYPES),
            "list_two": int(matcher_hits("permission_prompt|idle_prompt", "idle_prompt")),
            "list_miss": int(matcher_hits("permission_prompt|idle_prompt", "auth_success")),
        },
        {"empty": 14, "star": 14, "omitted": 14, "list_two": 1, "list_miss": 0},
    )

    denied = example_output(SAMPLE_MESSAGE)
    denied["continue"] = False
    denied["systemMessage"] = "denied"
    exit2 = settle(SAMPLE_MESSAGE, denied, 2)
    expect(
        "exit2_ignored",
        {
            "sent": exit2["sent"],
            "modified": exit2["modified"],
            "blocked": exit2["blocked"],
            "exit_ignored": exit2["exit_ignored"],
            "stderr_ignored": exit2["stderr_ignored"],
            "continue_applied": exit2["continue_applied"],
            "system_message_applied": exit2["system_message_applied"],
            "message": exit2["message"],
            "terminal_emitted": exit2["terminal_emitted"],
            "emitted_by": exit2["emitted_by"],
        },
        {
            "sent": 1,
            "modified": 0,
            "blocked": 0,
            "exit_ignored": 1,
            "stderr_ignored": 1,
            "continue_applied": 0,
            "system_message_applied": 0,
            "message": SAMPLE_MESSAGE,
            "terminal_emitted": 1,
            "emitted_by": "host",
        },
    )
    kept = settle(SAMPLE_MESSAGE, denied, 0)
    expect(
        "discard_keep_sequence",
        {
            "sent": kept["sent"],
            "modified": kept["modified"],
            "blocked": kept["blocked"],
            "continue_applied": kept["continue_applied"],
            "system_message_applied": kept["system_message_applied"],
            "terminal_emitted": kept["terminal_emitted"],
            "emitted_by": kept["emitted_by"],
            "slept": kept["slept"],
        },
        {
            "sent": 1,
            "modified": 0,
            "blocked": 0,
            "continue_applied": 0,
            "system_message_applied": 0,
            "terminal_emitted": 1,
            "emitted_by": "host",
            "slept": 0,
        },
    )
    quiet = settle(SAMPLE_MESSAGE, None, 0)
    expect(
        "empty_stdout",
        {
            "sent": quiet["sent"],
            "modified": quiet["modified"],
            "terminal_emitted": quiet["terminal_emitted"],
        },
        {"sent": 1, "modified": 0, "terminal_emitted": 0},
    )

    async_drop = settle(SAMPLE_MESSAGE, denied, 0, async_=True)
    rewake_drop = settle(SAMPLE_MESSAGE, denied, 0, async_rewake=True)
    expect(
        "async_drops_sequence",
        {
            "terminal_emitted": async_drop["terminal_emitted"],
            "emitted_by": async_drop["emitted_by"],
            "sent": async_drop["sent"],
            "continue_applied": async_drop["continue_applied"],
        },
        {
            "terminal_emitted": 0,
            "emitted_by": "none",
            "sent": 1,
            "continue_applied": 0,
        },
    )
    expect(
        "async_rewake_drops_sequence",
        {
            "terminal_emitted": rewake_drop["terminal_emitted"],
            "emitted_by": rewake_drop["emitted_by"],
            "sent": rewake_drop["sent"],
        },
        {"terminal_emitted": 0, "emitted_by": "none", "sent": 1},
    )
    dash_p = settle(SAMPLE_MESSAGE, denied, 0, dash_p=True)
    sdk_seq = settle(SAMPLE_MESSAGE, denied, 0, agent_sdk=True)
    closed = settle(SAMPLE_MESSAGE, denied, 0, interface_open=False)
    expect(
        "dash_p_ignores_sequence",
        {"terminal_emitted": dash_p["terminal_emitted"], "sent": dash_p["sent"]},
        {"terminal_emitted": 0, "sent": 1},
    )
    expect(
        "agent_sdk_ignores_sequence",
        {"terminal_emitted": sdk_seq["terminal_emitted"], "sent": sdk_seq["sent"]},
        {"terminal_emitted": 0, "sent": 1},
    )
    expect(
        "interface_closed",
        {"terminal_emitted": closed["terminal_emitted"]},
        {"terminal_emitted": 0},
    )

    progress = "\x1b]9;4;1\a"
    osc52 = "\x1b]52;c;aGVsbG8=\a"
    csi = "\x1b[31m"
    expect(
        "allowlist",
        {
            "osc777": int(sequence_allowed(osc777("Claude Code", SAMPLE_MESSAGE))),
            "osc0": int(sequence_allowed("\x1b]0;Claude Code\a")),
            "osc9_progress": int(sequence_allowed(progress)),
            "bel": int(sequence_allowed(BEL)),
            "osc52": int(sequence_allowed(osc52)),
            "csi": int(sequence_allowed(csi)),
            "mixed": int(sequence_allowed(osc777("Claude Code", SAMPLE_MESSAGE) + csi)),
        },
        {
            "osc777": 1,
            "osc0": 1,
            "osc9_progress": 1,
            "bel": 1,
            "osc52": 0,
            "csi": 0,
            "mixed": 0,
        },
    )
    rejected = settle(SAMPLE_MESSAGE, {"terminalSequence": csi}, 0)
    expect(
        "csi_rejected",
        {"terminal_emitted": rejected["terminal_emitted"], "emitted_by": rejected["emitted_by"]},
        {"terminal_emitted": 0, "emitted_by": "none"},
    )

    disabled = {
        "hook_ran": int(matcher_hits(None, SAMPLE_TYPE)),
        "stopped_by_channel": 0,
        "notifications_disabled": 1,
    }
    expect(
        "channel_disabled",
        disabled,
        {"hook_ran": 1, "stopped_by_channel": 0, "notifications_disabled": 1},
    )
    expect(
        "channel_disabled_idle",
        {
            "hook_ran": int(matcher_hits("", "idle_prompt")),
            "stopped_by_channel": 0,
        },
        {"hook_ran": 1, "stopped_by_channel": 0},
    )

    at_zero = permission_snapshot(now=0, kind="terminal")
    before = permission_snapshot(now=5, kind="terminal")
    at_six = permission_snapshot(now=6, kind="terminal")
    deferred = permission_snapshot(now=6, kind="terminal", keys=[4])
    deferred_later = permission_snapshot(now=10, kind="terminal", keys=[4])
    early_key = permission_snapshot(now=6, kind="terminal", keys=[-1])
    expect(
        "terminal_at_zero",
        {
            "permission_prompt": at_zero["permission_prompt"],
            "permission_request": at_zero["permission_request"],
            "permission_request_at": at_zero["permission_request_at"],
            "slept": at_zero["slept"],
        },
        {
            "permission_prompt": 0,
            "permission_request": 1,
            "permission_request_at": 0,
            "slept": 0,
        },
    )
    expect(
        "terminal_before_six",
        {
            "permission_prompt": before["permission_prompt"],
            "permission_request": before["permission_request"],
            "slept": before["slept"],
        },
        {"permission_prompt": 0, "permission_request": 1, "slept": 0},
    )
    expect(
        "terminal_at_six",
        {
            "permission_prompt": at_six["permission_prompt"],
            "permission_request": at_six["permission_request"],
            "permission_request_waited": at_six["permission_request_waited"],
            "slept": at_six["slept"],
        },
        {
            "permission_prompt": 1,
            "permission_request": 1,
            "permission_request_waited": 0,
            "slept": 0,
        },
    )
    expect(
        "terminal_key_defers",
        {
            "now6": deferred["permission_prompt"],
            "now10": deferred_later["permission_prompt"],
            "permission_request_at": deferred["permission_request_at"],
            "slept": deferred["slept"],
        },
        {"now6": 0, "now10": 1, "permission_request_at": 0, "slept": 0},
    )
    two_keys = permission_snapshot(now=10, kind="terminal", keys=[4, 7])
    two_keys_due = permission_snapshot(now=13, kind="terminal", keys=[4, 7])
    expect(
        "terminal_second_key",
        {
            "now10": two_keys["permission_prompt"],
            "now13": two_keys_due["permission_prompt"],
            "permission_request": two_keys["permission_request"],
        },
        {"now10": 0, "now13": 1, "permission_request": 1},
    )
    expect(
        "terminal_key_before_prompt",
        {"permission_prompt": early_key["permission_prompt"], "slept": 0},
        {"permission_prompt": 1, "slept": 0},
    )

    sdk_key = permission_snapshot(now=6, kind="sdk", keys=[4])
    sdk_early = permission_snapshot(now=5, kind="sdk", keys=[4])
    sdk_user = permission_snapshot(
        now=6, kind="sdk", answered_at=2, answered_by="user"
    )
    sdk_hook = permission_snapshot(
        now=6, kind="sdk", answered_at=0, answered_by="permission_request"
    )
    sdk_late = permission_snapshot(
        now=6, kind="sdk", answered_at=7, answered_by="user"
    )
    expect(
        "sdk_typing_no_defer",
        {
            "now5": sdk_early["permission_prompt"],
            "now6": sdk_key["permission_prompt"],
            "slept": sdk_key["slept"],
        },
        {"now5": 0, "now6": 1, "slept": 0},
    )
    expect(
        "sdk_user_answered",
        {
            "permission_prompt": sdk_user["permission_prompt"],
            "permission_request": sdk_user["permission_request"],
            "answered_by": sdk_user["answered_by"],
        },
        {"permission_prompt": 0, "permission_request": 1, "answered_by": "user"},
    )
    expect(
        "sdk_hook_answered",
        {
            "permission_prompt": sdk_hook["permission_prompt"],
            "permission_request": sdk_hook["permission_request"],
            "answered_by": sdk_hook["answered_by"],
        },
        {
            "permission_prompt": 0,
            "permission_request": 1,
            "answered_by": "permission_request",
        },
    )
    expect(
        "sdk_answered_after_due",
        {"permission_prompt": sdk_late["permission_prompt"]},
        {"permission_prompt": 1},
    )
    sdk_off = permission_snapshot(now=6, kind="sdk", disable=True)
    sdk_old = permission_snapshot(now=6, kind="sdk", version=(2, 1, 232))
    sdk_new = permission_snapshot(now=6, kind="sdk", version=(2, 1, 233))
    expect(
        "sdk_disable_flag",
        {"permission_prompt": sdk_off["permission_prompt"], "disable": 1},
        {"permission_prompt": 0, "disable": 1},
    )
    expect(
        "sdk_before_233",
        {"permission_prompt": sdk_old["permission_prompt"]},
        {"permission_prompt": 0},
    )
    expect(
        "sdk_at_233",
        {"permission_prompt": sdk_new["permission_prompt"]},
        {"permission_prompt": 1},
    )

    idle_59 = idle_fires(
        now=59,
        reply_at=0,
        typed_since=False,
        agent_running=False,
        in_usage_wait=False,
        usage_ended_on_its_own=False,
    )
    idle_60 = idle_fires(
        now=60,
        reply_at=0,
        typed_since=False,
        agent_running=False,
        in_usage_wait=False,
        usage_ended_on_its_own=False,
    )
    idle_typed = idle_fires(
        now=120,
        reply_at=0,
        typed_since=True,
        agent_running=False,
        in_usage_wait=False,
        usage_ended_on_its_own=False,
    )
    idle_agent = idle_fires(
        now=60,
        reply_at=0,
        typed_since=False,
        agent_running=True,
        in_usage_wait=False,
        usage_ended_on_its_own=False,
    )
    idle_agent_done = idle_fires(
        now=60,
        reply_at=0,
        typed_since=False,
        agent_running=False,
        in_usage_wait=False,
        usage_ended_on_its_own=False,
    )
    idle_wait = idle_fires(
        now=120,
        reply_at=0,
        typed_since=False,
        agent_running=False,
        in_usage_wait=True,
        usage_ended_on_its_own=False,
    )
    idle_ended = idle_fires(
        now=120,
        reply_at=0,
        typed_since=False,
        agent_running=False,
        in_usage_wait=False,
        usage_ended_on_its_own=True,
    )
    expect(
        "idle_before",
        {"idle_prompt": idle_59["idle_prompt"], "slept": idle_59["slept"]},
        {"idle_prompt": 0, "slept": 0},
    )
    expect(
        "idle_at_sixty",
        {"idle_prompt": idle_60["idle_prompt"], "slept": idle_60["slept"]},
        {"idle_prompt": 1, "slept": 0},
    )
    expect(
        "idle_typed",
        {"idle_prompt": idle_typed["idle_prompt"], "now": 120},
        {"idle_prompt": 0, "now": 120},
    )
    expect(
        "idle_agent_running",
        {"idle_prompt": idle_agent["idle_prompt"]},
        {"idle_prompt": 0},
    )
    expect(
        "idle_agent_stopped",
        {"idle_prompt": idle_agent_done["idle_prompt"]},
        {"idle_prompt": 1},
    )
    expect(
        "idle_usage_wait",
        {
            "idle_prompt": idle_wait["idle_prompt"],
            "quota_family": idle_wait["quota_family"],
        },
        {"idle_prompt": 0, "quota_family": 0},
    )
    expect(
        "idle_usage_ended",
        {
            "idle_prompt": idle_ended["idle_prompt"],
            "quota_family": idle_ended["quota_family"],
            "specific": idle_ended["specific"],
        },
        {"idle_prompt": 0, "quota_family": 1, "specific": "not_picked"},
    )

    ok = auth_type(True)
    bad_store = auth_type(False)
    expect(
        "auth_success",
        ok,
        {"auth_success": 1, "auth_storage_failure": 0, "both": 0},
    )
    expect(
        "auth_storage_failure",
        bad_store,
        {"auth_success": 0, "auth_storage_failure": 1, "both": 0},
    )

    sand_old = permission_snapshot(now=6, kind="terminal", sandbox=True, version=(2, 1, 245))
    sand_early = permission_snapshot(now=5, kind="terminal", sandbox=True, version=(2, 1, 246))
    sand_due = permission_snapshot(now=6, kind="terminal", sandbox=True, version=(2, 1, 246))
    expect(
        "sandbox_before_246",
        {
            "permission_request": sand_old["permission_request"],
            "permission_prompt": sand_old["permission_prompt"],
        },
        {"permission_request": 0, "permission_prompt": 0},
    )
    expect(
        "sandbox_before_six",
        {
            "permission_request": sand_early["permission_request"],
            "permission_prompt": sand_early["permission_prompt"],
        },
        {"permission_request": 0, "permission_prompt": 0},
    )
    expect(
        "sandbox_at_six",
        {
            "permission_request": sand_due["permission_request"],
            "permission_prompt": sand_due["permission_prompt"],
            "slept": sand_due["slept"],
        },
        {"permission_request": 0, "permission_prompt": 1, "slept": 0},
    )

    queued = permission_snapshot(now=6, kind="terminal", behind_dialog=True)
    queued_early = permission_snapshot(now=5, kind="terminal", behind_dialog=True)
    expect(
        "dialog_behind",
        {
            "now5": queued_early["permission_prompt"],
            "permission_prompt": queued["permission_prompt"],
            "notification_while_queued": queued["notification_while_queued"],
            "permission_request": queued["permission_request"],
            "slept": queued["slept"],
        },
        {
            "now5": 0,
            "permission_prompt": 1,
            "notification_while_queued": 1,
            "permission_request": 1,
            "slept": 0,
        },
    )
    expect(
        "elicitation_quiet",
        {
            "now5": int(5 >= SIX),
            "now6": int(6 >= SIX),
            "blocks": 0,
            "slept": 0,
        },
        {"now5": 0, "now6": 1, "blocks": 0, "slept": 0},
    )

    expect(
        "if_never_runs",
        {
            "notification_with_if": if_runs("Notification", True),
            "notification_without_if": if_runs("Notification", False),
            "permission_request_if_in_scope": if_runs("PermissionRequest", True),
        },
        {
            "notification_with_if": 0,
            "notification_without_if": 1,
            "permission_request_if_in_scope": 1,
        },
    )
    expect(
        "version_note",
        {"changelog_331_notification_item": CHANGELOG_331_NOTIFICATION_ITEM},
        {"changelog_331_notification_item": 0},
    )
    expect(
        "unread",
        {
            "terminal_answer_cancels": "not_stated",
            "other_channels": "not_stated",
            "disable_flag_in_terminal": "not_stated",
            "prompt_agent_outcome": "not_stated",
            "elicitation_keystroke": "not_stated",
            "quota_subtype": "not_picked",
            "terminal_answer_simulated": 0,
            "other_channels_simulated": 0,
            "disable_flag_terminal_simulated": 0,
            "prompt_agent_simulated": 0,
            "elicitation_keystroke_simulated": 0,
            "quota_subtype_simulated": 0,
        },
        {
            "terminal_answer_cancels": "not_stated",
            "other_channels": "not_stated",
            "disable_flag_in_terminal": "not_stated",
            "prompt_agent_outcome": "not_stated",
            "elicitation_keystroke": "not_stated",
            "quota_subtype": "not_picked",
            "terminal_answer_simulated": 0,
            "other_channels_simulated": 0,
            "disable_flag_terminal_simulated": 0,
            "prompt_agent_simulated": 0,
            "elicitation_keystroke_simulated": 0,
            "quota_subtype_simulated": 0,
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
