#!/usr/bin/env python3
"""本地夹具：elicitation 通知叫你回头，表单闸是 Elicitation / ElicitationResult。

不调用 API，不访问网络，不启动 Claude Code，不弹出 MCP 对话框，
不打开浏览器，不依赖 jq，也不睡眠。大约六秒只记成一个数。

这不是 settings 里的 hook，也不是 Claude Code 运行时。

输入输出按 2026-11-25 08:27（Asia/Shanghai）打开的 Hooks reference
（hooks.md）里 Elicitation、ElicitationResult 两节、matcher 表、退出码表、
Decision control 总表，以及 JSON 输出里「hookSpecificOutput 只在 exit 0
生效」那一条，在本地走一遍。hooks-guide 里「Elicitation 阻塞时看不到说明」
只作对照。

页上没写成可执行结果的格子 simulated=0，不算裁决：
同一请求里 accept 与 cancel 同时出现、没有 decline 时谁赢；
ElicitationResult 返回 cancel 时用户填的值还在不在回传里；
prompt / agent 配在这两只事件上是跳过还是报错；
elicitation 通知的按键是不是逐次推迟；
exit 不是 0 也不是 2 时对话框还出不出；
只打印会被丢掉的 reason / systemMessage / continue、没有 action 时，
算不算「无输出」。
顶层 decision 在 v2.1.105 到 v2.1.284 的修复之前曾被忽略。
夹具只模拟今天这一页：decision block 会 decline。不按版本分支。
"""

from __future__ import annotations

FAILS: list[str] = []

SESSION = "abc123"
TRANSCRIPT = "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl"
CWD = "/Users/..."

# 今天打开的 changelog 2.1.331 没有 Elicitation 专条。
# 两只事件在 2.1.76 加入。decision 的修复写在 2.1.284。
CHANGELOG_331_ELICITATION_ITEM = 0
EVENTS_ADDED = "2.1.76"
DECISION_FIX = "2.1.284"

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


def common_fields(event: str) -> dict:
    return {
        "session_id": SESSION,
        "transcript_path": TRANSCRIPT,
        "cwd": CWD,
        "hook_event_name": event,
    }


def form_request(
    server: str = "my-mcp-server",
    *,
    properties: dict | None = None,
    message: str = "Please provide your username",
    elicitation_id: str | None = None,
) -> dict:
    """form 模式。content 的键是 requested_schema.properties 里的名字。"""
    if properties is None:
        properties = {"username": {"type": "string", "title": "Username"}}
    payload = common_fields("Elicitation")
    payload.update(
        {
            "mcp_server_name": server,
            "message": message,
            "mode": "form",
            "requested_schema": {"type": "object", "properties": properties},
        }
    )
    if elicitation_id is not None:
        payload["elicitation_id"] = elicitation_id
    return payload


def url_request(server: str = "my-mcp-server") -> dict:
    payload = common_fields("Elicitation")
    payload.update(
        {
            "mcp_server_name": server,
            "message": "Please authenticate",
            "mode": "url",
            "url": "https://auth.example.com/login",
        }
    )
    return payload


def result_input(
    server: str,
    action: str,
    content: dict | None = None,
    mode: str = "form",
) -> dict:
    payload = common_fields("ElicitationResult")
    payload.update({"mcp_server_name": server, "action": action, "mode": mode})
    if content is not None:
        payload["content"] = content
    return payload


def matcher_hits(matcher: str | None, server_name: str) -> bool:
    """省略、空字符串、* 打全部服务器名。字母数字路径做精确或 |/, 列表。"""
    if matcher is None or matcher in ("", "*"):
        return True
    if all(char in EXACT_CHARS for char in matcher):
        parts = [part.strip() for part in matcher.replace(",", "|").split("|")]
        parts = [part for part in parts if part]
        return server_name in parts
    raise SystemExit("regex matchers are not simulated")


def if_runs(event: str, if_set: bool) -> int:
    """if 只在工具事件上求值。其他事件写了 if，这只钩子不跑。"""
    if not if_set:
        return 1
    if event in TOOL_EVENTS:
        return 1
    return 0


def specific_of(stdout: dict | None) -> dict:
    if not stdout:
        return {}
    value = stdout.get("hookSpecificOutput")
    if isinstance(value, dict):
        return value
    return {}


def hidden_fields(stdout: dict | None, stderr: str) -> dict:
    """reason、systemMessage、continue、stderr 都不交给用户或服务器。"""
    return {
        "reason_seen": 0,
        "system_message_seen": 0,
        "continue_applied": 0,
        "stderr_seen": 0,
        "stderr_len": len(stderr or ""),
        "had_reason": int(bool(stdout) and "reason" in stdout),
        "had_system_message": int(bool(stdout) and "systemMessage" in stdout),
        "had_continue": int(bool(stdout) and "continue" in stdout),
    }


def one_elicitation(hook: dict, request: dict) -> dict:
    """一只 Elicitation 钩子的表决。没跑、或没给 action，action 为 None。

    exit 2 忽略同一只钩子的 hookSpecificOutput，表决是 decline。
    exit 0 时，顶层 decision block 覆盖同一份输出里的 action。
    """
    event = request["hook_event_name"]
    if if_runs(event, bool(hook.get("if_set"))) == 0:
        return {"ran": 0, "action": None}
    if not matcher_hits(hook.get("matcher"), request["mcp_server_name"]):
        return {"ran": 0, "action": None}
    if "fn" in hook:
        code, stdout, stderr = hook["fn"](request)
    else:
        code = hook.get("exit", 0)
        stdout = hook.get("stdout")
        stderr = hook.get("stderr", "")
    if code not in (0, 2):
        raise SystemExit("exit codes other than 0 and 2 are not simulated")
    hidden = hidden_fields(stdout, stderr)
    if code == 2:
        return {
            "ran": 1,
            "action": "decline",
            "content": None,
            "specific_applied": 0,
            **hidden,
        }
    decision = (stdout or {}).get("decision")
    action = specific_of(stdout).get("action")
    content = specific_of(stdout).get("content")
    if decision == "block":
        return {
            "ran": 1,
            "action": "decline",
            "content": None,
            "specific_applied": 0,
            "overrode_action": action or "",
            **hidden,
        }
    if action in ("accept", "decline", "cancel"):
        return {
            "ran": 1,
            "action": action,
            "content": content if action == "accept" else None,
            "specific_applied": 1,
            **hidden,
        }
    return {"ran": 1, "action": None, "content": None, "specific_applied": 0, **hidden}


def combine(votes: list[dict]) -> dict | None:
    """多只钩子：一只 decline 盖过另一只的 accept 或 cancel。

    只有 accept、或只有 cancel 时采用那一票。
    两种同时出现、又没有 decline：页上没写谁赢，调用方不得猜。
    """
    decided = [vote for vote in votes if vote.get("action")]
    if any(vote["action"] == "decline" for vote in decided):
        return {"action": "decline", "content": None}
    accepts = [vote for vote in decided if vote["action"] == "accept"]
    cancels = [vote for vote in decided if vote["action"] == "cancel"]
    if accepts and cancels:
        return {"action": "not_stated", "content": None}
    if len(accepts) > 1 or len(cancels) > 1:
        return {"action": "not_stated", "content": None}
    if accepts:
        return {"action": "accept", "content": accepts[0].get("content")}
    if cancels:
        return {"action": "cancel", "content": None}
    return None


def one_result(hook: dict, incoming: dict, calls: list[str]) -> dict:
    """一只 ElicitationResult 钩子。无 action 的 hookSpecificOutput 被忽略。

    exit 2 同样忽略 hookSpecificOutput，回传的 action 变成 decline。
    顶层 decision block 覆盖同一份输出里的 action。
    """
    event = incoming["hook_event_name"]
    if if_runs(event, bool(hook.get("if_set"))) == 0:
        return {"ran": 0, "kind": "skip"}
    if not matcher_hits(hook.get("matcher"), incoming["mcp_server_name"]):
        return {"ran": 0, "kind": "skip"}
    calls.append(event)
    if "fn" in hook:
        code, stdout, stderr = hook["fn"](incoming)
    else:
        code = hook.get("exit", 0)
        stdout = hook.get("stdout")
        stderr = hook.get("stderr", "")
    if code not in (0, 2):
        raise SystemExit("exit codes other than 0 and 2 are not simulated")
    hidden = hidden_fields(stdout, stderr)
    if code == 2:
        return {"ran": 1, "kind": "decline", "specific_applied": 0, **hidden}
    decision = (stdout or {}).get("decision")
    action = specific_of(stdout).get("action")
    if decision == "block":
        return {
            "ran": 1,
            "kind": "decline",
            "specific_applied": 0,
            "overrode_action": action or "",
            **hidden,
        }
    if action is None:
        return {"ran": 1, "kind": "ignore", "specific_applied": 0, **hidden}
    if action == "accept":
        # 整份替换。没出现在这份 content 里的字段不保留。
        content = specific_of(stdout).get("content")
        replaced = dict(content) if isinstance(content, dict) else {}
        return {
            "ran": 1,
            "kind": "accept",
            "content": replaced,
            "specific_applied": 1,
            **hidden,
        }
    if action == "decline":
        return {"ran": 1, "kind": "decline", "specific_applied": 1, **hidden}
    if action == "cancel":
        return {"ran": 1, "kind": "cancel", "specific_applied": 1, **hidden}
    raise SystemExit(f"unexpected action {action!r}")


def apply_result(incoming: dict, hooks: list[dict]) -> dict:
    """用户已经答完。钩子可以放行、整份替换，或把 action 改成 decline / cancel。"""
    calls: list[str] = []
    votes = [one_result(hook, incoming, calls) for hook in hooks]
    kinds = [vote["kind"] for vote in votes if vote.get("ran")]
    user_content = incoming.get("content")
    base = {
        "result_calls": len(calls),
        "reason_seen": 0,
        "system_message_seen": 0,
        "continue_applied": 0,
        "stderr_seen": 0,
    }
    if "decline" in kinds:
        # decline 那一行：服务器收到 decline，没有用户填的值。
        return {
            **base,
            "server_action": "decline",
            "server_content": None,
            "user_values_sent": 0,
            "cancel_withholds": "n/a",
        }
    if "not_stated" in kinds:
        raise SystemExit("unreachable")
    accepts = [vote for vote in votes if vote.get("kind") == "accept"]
    cancels = [vote for vote in votes if vote.get("kind") == "cancel"]
    if accepts and cancels:
        return {
            **base,
            "server_action": "not_stated",
            "server_content": None,
            "user_values_sent": "not_stated",
            "cancel_withholds": "not_stated",
        }
    if len(accepts) > 1 or len(cancels) > 1:
        return {
            **base,
            "server_action": "not_stated",
            "server_content": None,
            "user_values_sent": "not_stated",
            "cancel_withholds": "not_stated",
        }
    if accepts:
        content = accepts[0]["content"]
        return {
            **base,
            "server_action": "accept",
            "server_content": content,
            "user_values_sent": int(content == user_content),
            "cancel_withholds": "n/a",
        }
    if cancels:
        # 要扣住用户提交的值，页上写的是返回 decline。cancel 扣不扣，不猜。
        return {
            **base,
            "server_action": "cancel",
            "server_content": None,
            "user_values_sent": "not_stated",
            "cancel_withholds": "not_stated",
        }
    return {
        **base,
        "server_action": incoming["action"],
        "server_content": user_content if isinstance(user_content, dict) else None,
        "user_values_sent": int(isinstance(user_content, dict)),
        "cancel_withholds": "n/a",
    }


def resolve(
    request: dict,
    elicitation_hooks: list[dict],
    user: dict | None = None,
    result_hooks: list[dict] | None = None,
) -> dict:
    """MCP 要输入。Elicitation 已给出结果时，不跑 ElicitationResult。

    钩子 answers a request（accept、decline 或 cancel，含 exit 2 与
    decision block）之后，答案直接发给服务器，对话框不出现。
    Result 写的是跑在用户作答之后。用户没再答，Result 的调用次数是 0。
    """
    if request.get("hook_event_name") != "Elicitation":
        raise SystemExit("resolve() only takes an Elicitation request")
    votes = [one_elicitation(hook, request) for hook in elicitation_hooks]
    chosen = combine(votes)
    hidden = {
        "reason_seen": 0,
        "system_message_seen": 0,
        "continue_applied": 0,
        "stderr_seen": 0,
    }
    ran = sum(vote.get("ran", 0) for vote in votes)
    if chosen and chosen["action"] == "not_stated":
        return {
            "elicitation_ran": ran,
            "dialog": "not_stated",
            "url_opened": "not_stated",
            "result_calls": 0,
            "server_action": "not_stated",
            "server_content": None,
            "user_values_sent": "not_stated",
            **hidden,
        }
    if chosen:
        url_opened = 0
        return {
            "elicitation_ran": ran,
            "dialog": 0,
            "url_opened": url_opened,
            "result_calls": 0,
            "server_action": chosen["action"],
            "server_content": chosen["content"],
            "user_values_sent": 0,
            **hidden,
        }
    # 无输出且 exit 0：留给对话框。用户答完之后才跑 Result。
    pending = {
        "elicitation_ran": ran,
        "dialog": 1,
        "url_opened": "user_path",
        "result_calls": 0,
        "server_action": "pending",
        "server_content": None,
        "user_values_sent": 0,
        **hidden,
    }
    if user is None:
        return pending
    incoming = result_input(
        request["mcp_server_name"],
        user["action"],
        user.get("content"),
        user.get("mode", request.get("mode", "form")),
    )
    settled = apply_result(incoming, result_hooks or [])
    return {
        "elicitation_ran": ran,
        "dialog": 1,
        "url_opened": "user_path",
        "result_calls": settled["result_calls"],
        "server_action": settled["server_action"],
        "server_content": settled["server_content"],
        "user_values_sent": settled["user_values_sent"],
        "reason_seen": settled["reason_seen"],
        "system_message_seen": settled["system_message_seen"],
        "continue_applied": settled["continue_applied"],
        "stderr_seen": settled["stderr_seen"],
    }


def content_text(content: dict | None) -> str:
    if content is None:
        return "none"
    parts = [f"{key}:{content[key]}" for key in sorted(content)]
    return ",".join(parts) if parts else "empty"


def view(outcome: dict) -> dict:
    shown = dict(outcome)
    shown["server_content"] = content_text(outcome.get("server_content"))
    return shown


def answer_project_key(payload: dict) -> tuple[int, dict | None, str]:
    """官方示例的契约：唯一字段是 project_key 就 accept 并填 DOCS。

    其他请求不打印，对话框出现。不调用 jq。
    """
    props = (payload.get("requested_schema") or {}).get("properties") or {}
    names = list(props.keys())
    if len(names) == 1 and names[0] == "project_key":
        return (
            0,
            {
                "hookSpecificOutput": {
                    "hookEventName": "Elicitation",
                    "action": "accept",
                    "content": {"project_key": "DOCS"},
                }
            },
            "",
        )
    return 0, None, ""


def decline_url(payload: dict) -> tuple[int, dict | None, str]:
    """官方示例：mode 为 url 就 exit 2，表单请求留给对话框。"""
    if payload.get("mode") == "url":
        return 2, None, "url mode declined"
    return 0, None, ""


def rewrite_username(payload: dict) -> tuple[int, dict | None, str]:
    """先看输入里的 action 是 accept，再把没改的字段一起带上。

    jq 的 + 发生在脚本里。交出去的 content 仍由宿主整份替换。
    输入不是 accept 时不打印。
    """
    if payload.get("action") != "accept":
        return 0, None, ""
    content = dict(payload.get("content") or {})
    content["username"] = f"{content.get('username', '')}@example.com"
    return (
        0,
        {
            "hookSpecificOutput": {
                "hookEventName": "ElicitationResult",
                "action": "accept",
                "content": content,
            }
        },
        "",
    )


def unsafe_accept(payload: dict) -> tuple[int, dict | None, str]:
    """不看输入 action 就返回 accept。用户的 decline / cancel 会被翻成接受。"""
    del payload
    return (
        0,
        {
            "hookSpecificOutput": {
                "hookEventName": "ElicitationResult",
                "action": "accept",
                "content": {"username": "hook"},
            }
        },
        "",
    )


def notification_side(notification_type: str, exit_code: int, stdout: dict) -> dict:
    """elicitation_dialog / elicitation_url_dialog 改不了这张表。

    大约六秒没打字才叫你。这里不睡眠。exit 2、顶层 decision、continue
    都不改这次 elicitation 的结局。Notification 没有 decision control。
    """
    del exit_code, stdout
    return {
        "notification_type": notification_type,
        "can_block": 0,
        "modified": 0,
        "request_declined": 0,
        "dialog_skipped_by_notification": 0,
        "slept": 0,
        "quiet_seconds": 6,
    }


def keys_of(payload: dict, names: tuple[str, ...]) -> dict:
    return {name: int(name in payload) for name in names}


def main() -> None:
    form = form_request()
    url = url_request()
    accepted = result_input(
        "my-mcp-server",
        "accept",
        {"username": "alice", "team": "docs"},
    )
    expect(
        "input_form",
        {
            **keys_of(
                form,
                (
                    "hook_event_name",
                    "mcp_server_name",
                    "message",
                    "requested_schema",
                ),
            ),
            "event": form["hook_event_name"],
            "mode": form["mode"],
            "schema_username": int("username" in form["requested_schema"]["properties"]),
        },
        {
            "hook_event_name": 1,
            "mcp_server_name": 1,
            "message": 1,
            "requested_schema": 1,
            "event": "Elicitation",
            "mode": "form",
            "schema_username": 1,
        },
    )
    expect(
        "input_url",
        {
            **keys_of(url, ("hook_event_name", "mcp_server_name", "message", "url")),
            "event": url["hook_event_name"],
            "mode": url["mode"],
        },
        {
            "hook_event_name": 1,
            "mcp_server_name": 1,
            "message": 1,
            "url": 1,
            "event": "Elicitation",
            "mode": "url",
        },
    )
    expect(
        "input_result",
        {
            **keys_of(
                accepted,
                ("hook_event_name", "mcp_server_name", "content", "mode"),
            ),
            "event": accepted["hook_event_name"],
            "action": accepted["action"],
        },
        {
            "hook_event_name": 1,
            "mcp_server_name": 1,
            "content": 1,
            "mode": 1,
            "event": "ElicitationResult",
            "action": "accept",
        },
    )

    matched = resolve(
        form_request("issue-tracker"),
        [{"matcher": "issue-tracker", "exit": 0, "stdout": None}],
    )
    missed = resolve(
        form_request("other-server"),
        [{"matcher": "issue-tracker", "exit": 0, "stdout": None}],
    )
    expect(
        "matcher_name",
        {"hit_ran": matched["elicitation_ran"], "miss_ran": missed["elicitation_ran"], "miss_dialog": missed["dialog"]},
        {"hit_ran": 1, "miss_ran": 0, "miss_dialog": 1},
    )
    empty_hits = []
    for matcher in (None, "", "*"):
        for server in ("issue-tracker", "other-server"):
            outcome = resolve(
                form_request(server),
                [{"matcher": matcher, "exit": 0, "stdout": None}],
            )
            empty_hits.append(outcome["elicitation_ran"])
    expect(
        "matcher_empty",
        {"hits": sum(empty_hits), "groups": len(empty_hits)},
        {"hits": 6, "groups": 6},
    )
    listed = resolve(
        form_request("docs"),
        [{"matcher": "issue-tracker|docs", "exit": 0, "stdout": None}],
    )
    listed_miss = resolve(
        form_request("other"),
        [{"matcher": "issue-tracker, docs", "exit": 0, "stdout": None}],
    )
    expect(
        "matcher_list",
        {"docs": listed["elicitation_ran"], "other": listed_miss["elicitation_ran"]},
        {"docs": 1, "other": 0},
    )

    accept_stdout = {
        "reason": "filled from the hook",
        "systemMessage": "answered",
        "continue": False,
        "hookSpecificOutput": {
            "hookEventName": "Elicitation",
            "action": "accept",
            "content": {"username": "alice"},
        },
    }
    spy_calls: list[str] = []

    def spy_decline(payload: dict) -> tuple[int, dict | None, str]:
        spy_calls.append(payload["hook_event_name"])
        return (
            0,
            {
                "hookSpecificOutput": {
                    "hookEventName": "ElicitationResult",
                    "action": "decline",
                }
            },
            "should not run",
        )

    answered = resolve(
        form,
        [{"matcher": None, "exit": 0, "stdout": accept_stdout, "stderr": "filled"}],
        user={"action": "accept", "content": {"username": "from-user"}},
        result_hooks=[{"matcher": None, "fn": spy_decline}],
    )
    expect(
        "accept_skips_dialog_and_result",
        view(answered),
        {
            "dialog": 0,
            "url_opened": 0,
            "result_calls": 0,
            "server_action": "accept",
            "server_content": "username:alice",
            "user_values_sent": 0,
            "reason_seen": 0,
            "system_message_seen": 0,
            "continue_applied": 0,
            "stderr_seen": 0,
        },
    )
    expect(
        "spy_not_called",
        {"calls": len(spy_calls)},
        {"calls": 0},
    )

    left = resolve(form, [{"matcher": None, "exit": 0, "stdout": None}])
    expect(
        "leave_to_dialog",
        view(left),
        {"dialog": 1, "server_action": "pending", "result_calls": 0, "elicitation_ran": 1},
    )

    url_accept = resolve(
        url,
        [
            {
                "matcher": "my-mcp-server",
                "exit": 0,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "Elicitation",
                        "action": "accept",
                    }
                },
            }
        ],
        result_hooks=[{"matcher": None, "fn": spy_decline}],
    )
    expect(
        "url_accept_skips_open",
        view(url_accept),
        {
            "dialog": 0,
            "url_opened": 0,
            "result_calls": 0,
            "server_action": "accept",
            "server_content": "none",
        },
    )

    exit2 = resolve(
        form,
        [
            {
                "matcher": None,
                "exit": 2,
                "stdout": accept_stdout,
                "stderr": "declined because the form is untrusted",
            }
        ],
        result_hooks=[{"matcher": None, "fn": spy_decline}],
    )
    expect(
        "exit2_declines_without_reason",
        view(exit2),
        {
            "dialog": 0,
            "server_action": "decline",
            "server_content": "none",
            "result_calls": 0,
            "reason_seen": 0,
            "stderr_seen": 0,
            "system_message_seen": 0,
            "continue_applied": 0,
            "user_values_sent": 0,
        },
    )

    blocked = resolve(
        form,
        [
            {
                "matcher": None,
                "exit": 0,
                "stdout": {"decision": "block", **accept_stdout},
                "stderr": "block",
            }
        ],
    )
    expect(
        "decision_block_overrides_action",
        view(blocked),
        {
            "dialog": 0,
            "server_action": "decline",
            "server_content": "none",
            "result_calls": 0,
            "reason_seen": 0,
        },
    )

    over_accept = resolve(
        form,
        [
            {"matcher": None, "exit": 0, "stdout": accept_stdout},
            {
                "matcher": None,
                "exit": 0,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "Elicitation",
                        "action": "decline",
                    }
                },
            },
        ],
    )
    over_cancel = resolve(
        url,
        [
            {
                "matcher": None,
                "exit": 0,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "Elicitation",
                        "action": "cancel",
                    }
                },
            },
            {"matcher": None, "exit": 2, "stdout": None, "stderr": "no"},
        ],
    )
    expect(
        "decline_overrides_accept",
        view(over_accept),
        {"dialog": 0, "server_action": "decline", "server_content": "none", "result_calls": 0},
    )
    expect(
        "decline_overrides_cancel",
        view(over_cancel),
        {"dialog": 0, "url_opened": 0, "server_action": "decline", "result_calls": 0},
    )
    expect(
        "accept_vs_cancel",
        {"winner": "not_stated", "simulated": 0},
        {"winner": "not_stated", "simulated": 0},
    )

    project = form_request(
        "issue-tracker",
        properties={"project_key": {"type": "string"}},
        message="Which project?",
    )
    filled = resolve(project, [{"matcher": "issue-tracker", "fn": answer_project_key}])
    other_field = resolve(
        form_request("issue-tracker"),
        [{"matcher": "issue-tracker", "fn": answer_project_key}],
    )
    other_server = resolve(
        form_request("other-server", properties={"project_key": {"type": "string"}}),
        [{"matcher": "issue-tracker", "fn": answer_project_key}],
    )
    expect(
        "script_project_key",
        view(filled),
        {"dialog": 0, "server_action": "accept", "server_content": "project_key:DOCS", "result_calls": 0},
    )
    expect(
        "script_other_field",
        view(other_field),
        {"dialog": 1, "server_action": "pending", "elicitation_ran": 1},
    )
    expect(
        "script_other_server",
        view(other_server),
        {"dialog": 1, "elicitation_ran": 0, "server_action": "pending"},
    )

    url_script = resolve(url, [{"matcher": None, "fn": decline_url}])
    form_script = resolve(form, [{"matcher": None, "fn": decline_url}])
    expect(
        "script_url_exit2",
        view(url_script),
        {"dialog": 0, "url_opened": 0, "server_action": "decline", "result_calls": 0, "stderr_seen": 0},
    )
    expect(
        "script_form_left",
        view(form_script),
        {"dialog": 1, "server_action": "pending", "elicitation_ran": 1},
    )

    user = {"action": "accept", "content": {"username": "alice", "team": "docs"}}
    passed = resolve(form, [], user=user, result_hooks=[{"matcher": None, "exit": 0, "stdout": None}])
    expect(
        "result_passthrough",
        view(passed),
        {
            "dialog": 1,
            "result_calls": 1,
            "server_action": "accept",
            "server_content": "team:docs,username:alice",
            "user_values_sent": 1,
        },
    )

    replaced = resolve(
        form,
        [],
        user=user,
        result_hooks=[
            {
                "matcher": "my-mcp-server",
                "exit": 0,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "action": "accept",
                        "content": {"username": "alice@example.com"},
                    }
                },
            }
        ],
    )
    expect(
        "result_replaces_whole_content",
        view(replaced),
        {
            "server_action": "accept",
            "server_content": "username:alice@example.com",
            "user_values_sent": 0,
            "result_calls": 1,
        },
    )
    kept = resolve(
        form,
        [],
        user=user,
        result_hooks=[{"matcher": None, "fn": rewrite_username}],
    )
    expect(
        "result_script_keeps_other_fields",
        view(kept),
        {
            "server_action": "accept",
            "server_content": "team:docs,username:alice@example.com",
            "result_calls": 1,
        },
    )

    ignored = resolve(
        form,
        [],
        user=user,
        result_hooks=[
            {
                "matcher": None,
                "exit": 0,
                "stdout": {
                    "reason": "ignored",
                    "systemMessage": "no",
                    "continue": False,
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "content": {"username": "bob"},
                    },
                },
                "stderr": "no action",
            }
        ],
    )
    expect(
        "result_without_action_ignored",
        view(ignored),
        {
            "server_action": "accept",
            "server_content": "team:docs,username:alice",
            "reason_seen": 0,
            "system_message_seen": 0,
            "continue_applied": 0,
            "stderr_seen": 0,
            "result_calls": 1,
        },
    )

    declined = resolve(
        form,
        [],
        user=user,
        result_hooks=[
            {
                "matcher": None,
                "exit": 0,
                "stdout": {
                    "reason": "withheld",
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "action": "decline",
                    },
                },
                "stderr": "withheld",
            }
        ],
    )
    expect(
        "result_decline_withholds",
        view(declined),
        {
            "server_action": "decline",
            "server_content": "none",
            "user_values_sent": 0,
            "reason_seen": 0,
            "stderr_seen": 0,
            "result_calls": 1,
        },
    )

    cancelled = apply_result(
        result_input("my-mcp-server", "accept", {"username": "alice", "team": "docs"}),
        [
            {
                "matcher": None,
                "exit": 0,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "action": "cancel",
                    }
                },
            }
        ],
    )
    expect(
        "result_cancel",
        {
            "server_action": cancelled["server_action"],
            "cancel_withholds": cancelled["cancel_withholds"],
            "result_calls": cancelled["result_calls"],
        },
        {"server_action": "cancel", "cancel_withholds": "not_stated", "result_calls": 1},
    )

    user_declined = {"action": "decline", "content": {"username": "alice"}}
    flipped = resolve(
        form,
        [],
        user=user_declined,
        result_hooks=[{"matcher": None, "fn": unsafe_accept}],
    )
    held = resolve(
        form,
        [],
        user=user_declined,
        result_hooks=[{"matcher": None, "fn": rewrite_username}],
    )
    expect(
        "result_runs_on_decline_and_can_flip",
        view(flipped),
        {
            "dialog": 1,
            "result_calls": 1,
            "server_action": "accept",
            "server_content": "username:hook",
        },
    )
    expect(
        "result_checks_action_before_accept",
        view(held),
        {
            "result_calls": 1,
            "server_action": "decline",
            "server_content": "username:alice",
        },
    )
    user_cancelled = {"action": "cancel", "content": {"username": "alice"}}
    flipped_cancel = resolve(
        form,
        [],
        user=user_cancelled,
        result_hooks=[{"matcher": None, "fn": unsafe_accept}],
    )
    held_cancel = resolve(
        form,
        [],
        user=user_cancelled,
        result_hooks=[{"matcher": None, "fn": rewrite_username}],
    )
    expect(
        "result_runs_on_cancel_and_can_flip",
        view(flipped_cancel),
        {"result_calls": 1, "server_action": "accept", "server_content": "username:hook"},
    )
    expect(
        "result_cancel_stays_when_checked",
        view(held_cancel),
        {"result_calls": 1, "server_action": "cancel", "server_content": "username:alice"},
    )

    exit2_result = apply_result(
        accepted,
        [
            {
                "matcher": None,
                "exit": 2,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "action": "accept",
                        "content": {"username": "alice@example.com", "team": "docs"},
                    }
                },
                "stderr": "blocked on the way back",
            }
        ],
    )
    expect(
        "result_exit2_becomes_decline",
        {
            "server_action": exit2_result["server_action"],
            "server_content": content_text(exit2_result["server_content"]),
            "user_values_sent": exit2_result["user_values_sent"],
            "stderr_seen": exit2_result["stderr_seen"],
        },
        {
            "server_action": "decline",
            "server_content": "none",
            "user_values_sent": 0,
            "stderr_seen": 0,
        },
    )
    decision_result = apply_result(
        accepted,
        [
            {
                "matcher": None,
                "exit": 0,
                "stdout": {
                    "decision": "block",
                    "reason": "no",
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "action": "accept",
                        "content": {"username": "alice@example.com"},
                    },
                },
            }
        ],
    )
    expect(
        "result_decision_block_overrides",
        {
            "server_action": decision_result["server_action"],
            "server_content": content_text(decision_result["server_content"]),
            "user_values_sent": decision_result["user_values_sent"],
            "reason_seen": decision_result["reason_seen"],
        },
        {
            "server_action": "decline",
            "server_content": "none",
            "user_values_sent": 0,
            "reason_seen": 0,
        },
    )

    result_override = apply_result(
        accepted,
        [
            {
                "matcher": None,
                "exit": 0,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "action": "accept",
                        "content": {"username": "alice@example.com", "team": "docs"},
                    }
                },
            },
            {
                "matcher": None,
                "exit": 0,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "action": "decline",
                    }
                },
            },
        ],
    )
    expect(
        "result_decline_overrides_accept",
        {
            "server_action": result_override["server_action"],
            "user_values_sent": result_override["user_values_sent"],
            "result_calls": result_override["result_calls"],
        },
        {"server_action": "decline", "user_values_sent": 0, "result_calls": 2},
    )

    missed_result = apply_result(
        accepted,
        [
            {
                "matcher": "issue-tracker",
                "exit": 0,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "action": "decline",
                    }
                },
            }
        ],
    )
    expect(
        "result_matcher_miss",
        {
            "server_action": missed_result["server_action"],
            "server_content": content_text(missed_result["server_content"]),
            "result_calls": missed_result["result_calls"],
        },
        {
            "server_action": "accept",
            "server_content": "team:docs,username:alice",
            "result_calls": 0,
        },
    )

    with_if = resolve(
        form,
        [
            {
                "matcher": None,
                "if_set": True,
                "exit": 0,
                "stdout": accept_stdout,
            }
        ],
    )
    result_if = apply_result(
        accepted,
        [
            {
                "matcher": None,
                "if_set": True,
                "exit": 0,
                "stdout": {
                    "hookSpecificOutput": {
                        "hookEventName": "ElicitationResult",
                        "action": "decline",
                    }
                },
            }
        ],
    )
    expect(
        "if_never_runs",
        {
            "elicitation_ran": with_if["elicitation_ran"],
            "dialog": with_if["dialog"],
            "result_calls": result_if["result_calls"],
            "server_action": result_if["server_action"],
        },
        {"elicitation_ran": 0, "dialog": 1, "result_calls": 0, "server_action": "accept"},
    )

    identified = form_request(elicitation_id="elic_1")
    id_outcome = resolve(
        identified,
        [{"matcher": None, "exit": 0, "stdout": accept_stdout}],
    )
    expect(
        "optional_elicitation_id",
        {
            "has_id": int("elicitation_id" in identified),
            "server_action": id_outcome["server_action"],
            "dialog": id_outcome["dialog"],
        },
        {"has_id": 1, "server_action": "accept", "dialog": 0},
    )

    for kind in ("elicitation_dialog", "elicitation_url_dialog"):
        side = notification_side(
            kind,
            2,
            {
                "decision": "block",
                "continue": False,
                "systemMessage": "stop the form",
                "reason": "notification is not a gate",
            },
        )
        expect(
            f"side_{kind}",
            side,
            {
                "notification_type": kind,
                "can_block": 0,
                "modified": 0,
                "request_declined": 0,
                "dialog_skipped_by_notification": 0,
                "slept": 0,
                "quiet_seconds": 6,
            },
        )

    expect(
        "version_note",
        {
            "changelog_331_elicitation_item": CHANGELOG_331_ELICITATION_ITEM,
            "events_added": EVENTS_ADDED,
            "decision_fix": DECISION_FIX,
            "pre_fix_ignore_simulated": 0,
        },
        {
            "changelog_331_elicitation_item": 0,
            "events_added": "2.1.76",
            "decision_fix": "2.1.284",
            "pre_fix_ignore_simulated": 0,
        },
    )
    expect(
        "unread",
        {
            "accept_vs_cancel": "not_stated",
            "cancel_withholds": "not_stated",
            "prompt_agent_outcome": "not_stated",
            "elicitation_keystroke": "not_stated",
            "other_exit": "not_stated",
            "discarded_only_output": "not_stated",
            "accept_vs_cancel_simulated": 0,
            "cancel_withholds_simulated": 0,
            "prompt_agent_simulated": 0,
            "elicitation_keystroke_simulated": 0,
            "other_exit_simulated": 0,
            "discarded_only_simulated": 0,
        },
        {
            "accept_vs_cancel": "not_stated",
            "cancel_withholds": "not_stated",
            "prompt_agent_outcome": "not_stated",
            "elicitation_keystroke": "not_stated",
            "other_exit": "not_stated",
            "discarded_only_output": "not_stated",
            "accept_vs_cancel_simulated": 0,
            "cancel_withholds_simulated": 0,
            "prompt_agent_simulated": 0,
            "elicitation_keystroke_simulated": 0,
            "other_exit_simulated": 0,
            "discarded_only_simulated": 0,
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
