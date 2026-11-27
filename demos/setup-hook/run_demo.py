#!/usr/bin/env python3
"""本地夹具：Setup 不是每场都会跑的准备钩子。

按 2026-11-27 08:35（Asia/Shanghai）打开的 Hooks reference（hooks.md）
里 Setup 一节、matcher 规则、退出码表、Decision control 总表、
「Events that fire before MCP servers are available」，
cli-reference 的 --init / --init-only / --maintenance / --debug-file /
--include-hook-events，headless 的 Read session metadata，
以及 plugins/components 里挂在 SessionStart 上的安装命令，在本地走一遍。

不调用 API，不访问网络，不启动 Claude Code，不执行 npm install，不读密钥，
不依赖 jq。这不是 settings 里的 hook，也不是 Claude Code 运行时。

夹具按这些页上的契约模拟。2.1.10 引入 Setup、当前最新正式版仍是 v2.1.332，
写在 README，不探测本机版本。

页上没写成可执行结果的格子 simulated=0，不算裁决：
hook_response 在 SDK 类型页上的完整字段表（hooks 与 headless 只点名事件，
并写明 stdout、stderr、退出码会出现在里面）；
--debug-file 日志里 Setup / SessionStart 条目的整行格式；
fork 时 SessionStart 的 mcp_tool 跑不跑（页上把「稍后会跑」点名在 /clear
和 compaction）；
--init-only 在钩子退出码不是成功时，终端会不会多印一行（「什么都不印」写在成功时）；
-p 缺 prompt 时的报错原文。
"""

from __future__ import annotations

import json
import re
import sys

FAILS: list[str] = []
NETWORK = 0
NPM_INVOKED = 0
CLAUDE_INVOKED = 0
RUNTIME_VERSION_PROBE = 0

EXACT_MATCHER_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ,|"
)

MCP_SKIP = (
    "mcp_tool hooks are not available for the '{event}' hook event "
    "(no MCP client context)"
)

COMMON_INPUT = {
    "session_id": "abc123",
    "transcript_path": (
        "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl"
    ),
    "cwd": "/Users/...",
}

SETUP_HOOKS = [
    {"id": "setup-init", "type": "command", "matcher": "init"},
    {"id": "setup-maint", "type": "command", "matcher": "maintenance"},
    {"id": "setup-both", "type": "command", "matcher": "init|maintenance"},
    {"id": "setup-mcp", "type": "mcp_tool", "matcher": "*"},
    {"id": "setup-http", "type": "http", "matcher": "*"},
    {"id": "setup-prompt", "type": "prompt", "matcher": "*"},
    {"id": "setup-agent", "type": "agent", "matcher": "*"},
]

SESSION_HOOKS = [
    {"id": "ss-startup", "type": "command", "matcher": "startup"},
    {"id": "ss-resume", "type": "command", "matcher": "resume"},
    {"id": "ss-clear", "type": "command", "matcher": "clear"},
    {"id": "ss-compact", "type": "command", "matcher": "compact"},
    {"id": "ss-fork", "type": "command", "matcher": "fork"},
    {"id": "ss-mcp", "type": "mcp_tool", "matcher": "*"},
]

# fork 的 mcp_tool 页上没有单独一句。0 表示不把「会跑」或「跳过」当成裁决。
LAUNCH = {
    "claude": {
        "setup_trigger": None,
        "source": "startup",
        "conversation": 1,
        "print_mode": 0,
        "sessionstart_mcp": 0,
        "fork_mcp": 0,
    },
    "resume": {
        "setup_trigger": None,
        "source": "resume",
        "conversation": 1,
        "print_mode": 0,
        "sessionstart_mcp": 0,
        "fork_mcp": 0,
    },
    "clear": {
        "setup_trigger": None,
        "source": "clear",
        "conversation": 1,
        "print_mode": 0,
        "sessionstart_mcp": 1,
        "fork_mcp": 0,
    },
    "compact": {
        "setup_trigger": None,
        "source": "compact",
        "conversation": 1,
        "print_mode": 0,
        "sessionstart_mcp": 1,
        "fork_mcp": 0,
    },
    "fork": {
        "setup_trigger": None,
        "source": "fork",
        "conversation": 1,
        "print_mode": 0,
        "sessionstart_mcp": 0,
        "fork_mcp": 1,
    },
    "init_only": {
        "setup_trigger": "init",
        "source": "startup",
        "conversation": 0,
        "print_mode": 0,
        "sessionstart_mcp": 0,
        "fork_mcp": 0,
    },
    "print_init": {
        "setup_trigger": "init",
        "source": "startup",
        "conversation": 1,
        "print_mode": 1,
        "sessionstart_mcp": 0,
        "fork_mcp": 0,
    },
    "print_maintenance": {
        "setup_trigger": "maintenance",
        "source": "startup",
        "conversation": 1,
        "print_mode": 1,
        "sessionstart_mcp": 0,
        "fork_mcp": 0,
    },
    "print_plain": {
        "setup_trigger": None,
        "source": "startup",
        "conversation": 1,
        "print_mode": 1,
        "sessionstart_mcp": 0,
        "fork_mcp": 0,
    },
}


def expect(name: str, actual: dict, expected: dict) -> None:
    bad = []
    for key, want in expected.items():
        got = actual.get(key, "<missing>")
        if got != want:
            bad.append(f"{key}: got {got!r} want {want!r}")
    if bad:
        FAILS.append(name + " | " + "; ".join(bad))
    shown = " ".join(f"{key}={actual.get(key, '<missing>')}" for key in expected)
    print(f"case={name} {shown}")


def matcher_hits(matcher: str | None, value: str) -> bool:
    """只走参考页的精确名单。含其它字符的正则路径不模拟。"""
    if matcher is None or matcher == "" or matcher == "*":
        return True
    if any(ch not in EXACT_MATCHER_CHARS for ch in matcher):
        raise RuntimeError("regex matcher is not simulated")
    parts = [part.strip() for part in re.split(r"[|,]", matcher) if part.strip()]
    return value in parts


def setup_input(trigger: str) -> dict:
    payload = dict(COMMON_INPUT)
    payload["hook_event_name"] = "Setup"
    payload["trigger"] = trigger
    return payload


def input_ok(payload: dict) -> int:
    required = ("session_id", "transcript_path", "cwd", "hook_event_name", "trigger")
    if any(key not in payload for key in required):
        return 0
    if payload["hook_event_name"] != "Setup":
        return 0
    if payload["trigger"] not in ("init", "maintenance"):
        return 0
    return 1


def classify_setup_output(stdout: dict | None, exit_code: int) -> dict:
    """任何退出码都继续。JSON 输出字段丢掉，不能当成注入或中止。"""
    discarded: list[str] = []
    if isinstance(stdout, dict):
        for key in ("systemMessage", "continue", "decision"):
            if key in stdout:
                discarded.append(key)
        if "additionalContext" in stdout:
            discarded.append("additionalContext")
        nested = stdout.get("hookSpecificOutput")
        if isinstance(nested, dict) and "additionalContext" in nested:
            discarded.append("hookSpecificOutput.additionalContext")
    return {
        "continued": 1,
        "blocked": 0,
        "injected_context": 0,
        "discarded": ",".join(discarded),
        "exit_code": exit_code,
    }


def run_launch(kind: str, **opts) -> dict:
    spec = LAUNCH[kind]
    trigger = spec["setup_trigger"]
    source = spec["source"]
    debug: list[str] = []
    setup_command: list[str] = []
    setup_mcp_skipped: list[str] = []
    setup_type_skipped: list[str] = []
    session_command: list[str] = []
    session_mcp_calls = 0
    session_mcp_skipped = 0
    fork_mcp_simulated = 0 if spec["fork_mcp"] else 1

    stdout = opts.get("setup_stdout")
    exit_code = int(opts.get("setup_exit", 0))
    stderr = opts.get("setup_stderr", "")
    plain = opts.get("setup_plain", "")
    if stdout is not None and plain:
        raise RuntimeError("pass JSON stdout or plain stdout, not both")
    raw_stdout = plain
    if stdout is not None:
        raw_stdout = json.dumps(stdout, ensure_ascii=False, separators=(",", ":"))

    if trigger is not None:
        debug.append("event=Setup")
        for hook in SETUP_HOOKS:
            if not matcher_hits(hook["matcher"], trigger):
                continue
            if hook["type"] == "mcp_tool":
                setup_mcp_skipped.append(hook["id"])
                debug.append(MCP_SKIP.format(event="Setup"))
                continue
            if hook["type"] != "command":
                setup_type_skipped.append(hook["id"])
                continue
            setup_command.append(hook["id"])

    debug.append("event=SessionStart")
    mcp_later = spec["sessionstart_mcp"] == 1
    for hook in SESSION_HOOKS:
        if not matcher_hits(hook["matcher"], source):
            continue
        if hook["type"] == "mcp_tool":
            if spec["fork_mcp"]:
                fork_mcp_simulated = 0
                continue
            if mcp_later:
                session_mcp_calls += 1
            else:
                session_mcp_skipped += 1
                debug.append(MCP_SKIP.format(event="SessionStart"))
            continue
        if hook["type"] == "command":
            session_command.append(hook["id"])

    judged = classify_setup_output(stdout if trigger is not None else None, exit_code if trigger else 0)
    success_empty = (
        trigger is not None
        and spec["conversation"] == 0
        and exit_code == 0
        and stderr == ""
        and raw_stdout == ""
        and stdout is None
    )
    terminal = ""
    if success_empty:
        terminal = ""
    terminal_exact = 1 if success_empty or trigger is None else 0

    prompt = opts.get("prompt", "")
    if spec["print_mode"]:
        needs_prompt = 0 if prompt else 1
    else:
        needs_prompt = 0

    fmt = opts.get("output_format", "text")
    verbose = int(opts.get("verbose", 0))
    include_flag = int(opts.get("include_hook_events", 0))
    hook_response = 0
    hr_stdout = ""
    hr_stderr = ""
    hr_exit = ""
    if (
        spec["print_mode"]
        and trigger is not None
        and fmt == "stream-json"
        and verbose == 1
    ):
        hook_response = 1
        hr_stdout = raw_stdout
        hr_stderr = stderr
        hr_exit = str(exit_code)

    shell = opts.get("shell", "bash")
    write_env = int(opts.get("write_env", 0))
    env_file = 0
    subsequent_bash = 0
    bash_sees = 0
    if write_env and setup_command:
        if shell == "powershell":
            env_file = 0
        elif spec["conversation"] == 1:
            env_file = 1
            subsequent_bash = 1
            bash_sees = 1
        else:
            env_file = 1
            subsequent_bash = 0
            bash_sees = 0

    terminal_has_stdio = 1 if raw_stdout and raw_stdout in terminal else 0
    if stderr and stderr in terminal:
        terminal_has_stdio = 1

    return {
        "setup_trigger": trigger or "",
        "source": source,
        "setup_command_calls": len(setup_command),
        "setup_command_ids": ",".join(setup_command),
        "setup_mcp_calls": 0,
        "setup_mcp_skipped": len(setup_mcp_skipped),
        "setup_type_skipped": len(setup_type_skipped),
        "session_command_calls": len(session_command),
        "session_command_ids": ",".join(session_command),
        "session_mcp_calls": session_mcp_calls,
        "session_mcp_skipped": session_mcp_skipped,
        "fork_mcp_simulated": fork_mcp_simulated,
        "conversation": spec["conversation"],
        "terminal": terminal,
        "terminal_exact": terminal_exact,
        "terminal_has_stdio": terminal_has_stdio,
        "user_notice": 0,
        "debug_has_setup": 1 if "event=Setup" in debug else 0,
        "debug_has_sessionstart": 1 if "event=SessionStart" in debug else 0,
        "debug_mcp_setup": 1 if MCP_SKIP.format(event="Setup") in debug else 0,
        "debug_mcp_sessionstart": 1 if MCP_SKIP.format(event="SessionStart") in debug else 0,
        "continued": judged["continued"] if trigger is not None else 1,
        "blocked": judged["blocked"] if trigger is not None else 0,
        "injected_context": 0,
        "discarded": judged["discarded"] if trigger is not None else "",
        "hook_response": hook_response,
        "hook_response_stdout": hr_stdout,
        "hook_response_stderr": hr_stderr,
        "hook_response_exit": hr_exit,
        "include_flag_required": 0,
        "include_flag_seen": include_flag,
        "needs_prompt": needs_prompt,
        "prompt_error_exact": 0,
        "env_file": env_file,
        "subsequent_bash": subsequent_bash,
        "bash_sees": bash_sees,
        "print_mode": spec["print_mode"],
    }


def plugin_setup_only(kind: str) -> dict:
    """安装脚本只挂在 Setup 的 init 上。不调用 npm。"""
    trigger = LAUNCH[kind]["setup_trigger"]
    ran = 1 if trigger == "init" else 0
    return {
        "setup_ran": ran,
        "would_install": ran,
        "npm_invoked": 0,
        "conversation": LAUNCH[kind]["conversation"],
    }


def plugin_sessionstart_node_modules(present: int) -> dict:
    """hooks 参考举的例子：看 node_modules，没有再装。不调用 npm。"""
    return {
        "session_ran": 1,
        "would_install": 0 if present else 1,
        "npm_invoked": 0,
        "setup_ran": 0,
    }


def plugin_sessionstart_package_json(same: int) -> dict:
    """components 页的命令：两份 package.json 不一致才装。不调用 npm。"""
    return {
        "session_ran": 1,
        "would_install": 0 if same else 1,
        "npm_invoked": 0,
        "setup_ran": 0,
    }


def main() -> None:
    example_init = setup_input("init")
    expect(
        "input_example_init",
        {
            "ok": input_ok(example_init),
            "hook_event_name": example_init["hook_event_name"],
            "trigger": example_init["trigger"],
            "session_id": example_init["session_id"],
            "has_cwd": 1 if example_init.get("cwd") else 0,
        },
        {
            "ok": 1,
            "hook_event_name": "Setup",
            "trigger": "init",
            "session_id": "abc123",
            "has_cwd": 1,
        },
    )
    example_maint = setup_input("maintenance")
    expect(
        "input_example_maintenance",
        {"ok": input_ok(example_maint), "trigger": example_maint["trigger"]},
        {"ok": 1, "trigger": "maintenance"},
    )
    bad = setup_input("startup")
    expect(
        "input_rejects_sessionstart_trigger",
        {"ok": input_ok(bad), "trigger": bad["trigger"]},
        {"ok": 0, "trigger": "startup"},
    )

    init_only = run_launch("init_only")
    expect(
        "init_only_runs_setup_and_startup_then_exits",
        init_only,
        {
            "setup_trigger": "init",
            "setup_command_ids": "setup-init,setup-both",
            "session_command_ids": "ss-startup",
            "conversation": 0,
            "terminal": "",
            "terminal_exact": 1,
            "terminal_has_stdio": 0,
            "debug_has_setup": 1,
            "debug_has_sessionstart": 1,
            "needs_prompt": 0,
            "print_mode": 0,
        },
    )

    print_init = run_launch("print_init", prompt="query")
    expect(
        "print_init_matcher",
        print_init,
        {
            "setup_trigger": "init",
            "setup_command_ids": "setup-init,setup-both",
            "session_command_ids": "ss-startup",
            "conversation": 1,
            "needs_prompt": 0,
            "print_mode": 1,
        },
    )
    print_maint = run_launch("print_maintenance", prompt="query")
    expect(
        "print_maintenance_matcher",
        print_maint,
        {
            "setup_trigger": "maintenance",
            "setup_command_ids": "setup-maint,setup-both",
            "session_command_ids": "ss-startup",
            "conversation": 1,
        },
    )
    expect(
        "init_matcher_skips_maintenance_hook",
        {"maint": 1 if "setup-maint" in init_only["setup_command_ids"].split(",") else 0},
        {"maint": 0},
    )
    expect(
        "maintenance_matcher_skips_init_hook",
        {"init": 1 if "setup-init" in print_maint["setup_command_ids"].split(",") else 0},
        {"init": 0},
    )

    for kind, source in (
        ("claude", "startup"),
        ("resume", "resume"),
        ("clear", "clear"),
        ("compact", "compact"),
        ("fork", "fork"),
        ("print_plain", "startup"),
    ):
        got = run_launch(kind, prompt="query")
        expect(
            f"no_setup_on_{kind}",
            got,
            {
                "setup_command_calls": 0,
                "setup_mcp_skipped": 0,
                "debug_has_setup": 0,
                "source": source,
                "session_command_calls": 1,
                "conversation": 1,
            },
        )

    fork = run_launch("fork")
    expect(
        "fork_mcp_not_stated",
        fork,
        {"setup_command_calls": 0, "fork_mcp_simulated": 0, "source": "fork"},
    )

    payload = {
        "systemMessage": "ready",
        "continue": False,
        "decision": "block",
        "reason": "stop",
        "additionalContext": "top",
        "hookSpecificOutput": {
            "hookEventName": "Setup",
            "additionalContext": "nested",
        },
    }
    blocked = run_launch("print_init", prompt="query", setup_stdout=payload, setup_exit=0)
    expect(
        "json_fields_discarded",
        blocked,
        {
            "continued": 1,
            "blocked": 0,
            "injected_context": 0,
            "conversation": 1,
            "discarded": (
                "systemMessage,continue,decision,additionalContext,"
                "hookSpecificOutput.additionalContext"
            ),
        },
    )
    for code, stderr in ((0, ""), (1, "boom"), (2, "nope")):
        got = run_launch(
            "init_only",
            setup_exit=code,
            setup_stderr=stderr,
            setup_plain="hook-said" if code else "",
        )
        expect(
            f"exit_{code}_continues",
            got,
            {
                "continued": 1,
                "blocked": 0,
                "injected_context": 0,
                "user_notice": 0,
                "conversation": 0,
            },
        )
    success = run_launch("init_only")
    expect(
        "init_only_success_prints_nothing",
        success,
        {"terminal": "", "terminal_exact": 1, "user_notice": 0},
    )
    noisy = run_launch("init_only", setup_exit=2, setup_stderr="nope")
    expect(
        "init_only_nonsuccess_terminal_not_stated",
        noisy,
        {"terminal_exact": 0, "blocked": 0, "continued": 1},
    )

    hidden = run_launch(
        "print_init",
        prompt="query",
        setup_exit=2,
        setup_stderr="nope",
        setup_plain="hook-said",
        output_format="text",
        verbose=0,
        include_hook_events=0,
    )
    expect(
        "plain_terminal_hides_stdio",
        hidden,
        {
            "terminal_has_stdio": 0,
            "hook_response": 0,
            "include_flag_required": 0,
            "user_notice": 0,
        },
    )
    missing_verbose = run_launch(
        "print_init",
        prompt="query",
        setup_exit=2,
        setup_stderr="nope",
        setup_plain="hook-said",
        output_format="stream-json",
        verbose=0,
    )
    expect(
        "stream_json_without_verbose_hides_stdio",
        missing_verbose,
        {"hook_response": 0, "terminal_has_stdio": 0},
    )
    visible = run_launch(
        "print_init",
        prompt="query",
        setup_exit=2,
        setup_stderr="nope",
        setup_plain="hook-said",
        output_format="stream-json",
        verbose=1,
        include_hook_events=0,
    )
    expect(
        "stream_json_verbose_hook_response",
        visible,
        {
            "hook_response": 1,
            "hook_response_stdout": "hook-said",
            "hook_response_stderr": "nope",
            "hook_response_exit": "2",
            "injected_context": 0,
            "blocked": 0,
            "include_flag_required": 0,
            "include_flag_seen": 0,
            "terminal_has_stdio": 0,
        },
    )

    mcp = run_launch("init_only")
    expect(
        "mcp_tool_skipped_on_setup",
        mcp,
        {
            "setup_mcp_calls": 0,
            "setup_mcp_skipped": 1,
            "debug_mcp_setup": 1,
            "setup_type_skipped": 3,
        },
    )
    launched = run_launch("claude")
    cleared = run_launch("clear")
    expect(
        "sessionstart_mcp_skipped_at_launch",
        launched,
        {"session_mcp_calls": 0, "session_mcp_skipped": 1, "debug_mcp_sessionstart": 1},
    )
    expect(
        "sessionstart_mcp_runs_after_clear",
        cleared,
        {"session_mcp_calls": 1, "session_mcp_skipped": 0, "debug_mcp_sessionstart": 0},
    )
    compacted = run_launch("compact")
    expect(
        "sessionstart_mcp_runs_after_compact",
        compacted,
        {"session_mcp_calls": 1, "setup_command_calls": 0},
    )

    env_print = run_launch("print_init", prompt="query", write_env=1, shell="bash")
    expect(
        "env_reaches_later_bash_on_print_init",
        env_print,
        {"env_file": 1, "subsequent_bash": 1, "bash_sees": 1},
    )
    env_only = run_launch("init_only", write_env=1, shell="bash")
    expect(
        "env_no_later_bash_on_init_only",
        env_only,
        {"env_file": 1, "subsequent_bash": 0, "bash_sees": 0, "conversation": 0},
    )
    env_ps = run_launch("print_init", prompt="query", write_env=1, shell="powershell")
    expect(
        "powershell_no_env_file",
        env_ps,
        {"env_file": 0, "subsequent_bash": 0, "bash_sees": 0},
    )
    env_daily = run_launch("claude", write_env=1, shell="bash")
    expect(
        "everyday_setup_does_not_write_env",
        env_daily,
        {"env_file": 0, "setup_command_calls": 0},
    )

    bare = run_launch("print_init", prompt="")
    expect(
        "print_init_needs_prompt",
        bare,
        {"needs_prompt": 1, "prompt_error_exact": 0, "print_mode": 1},
    )
    expect(
        "init_only_does_not_need_prompt",
        run_launch("init_only", prompt=""),
        {"needs_prompt": 0, "conversation": 0},
    )

    everyday_plugin = plugin_setup_only("claude")
    expect(
        "plugin_setup_only_misses_everyday",
        everyday_plugin,
        {"setup_ran": 0, "would_install": 0, "npm_invoked": 0},
    )
    init_plugin = plugin_setup_only("init_only")
    expect(
        "plugin_setup_only_would_on_init_only",
        init_plugin,
        {"setup_ran": 1, "would_install": 1, "npm_invoked": 0, "conversation": 0},
    )
    resume_plugin = plugin_setup_only("resume")
    expect(
        "plugin_setup_only_misses_resume",
        resume_plugin,
        {"setup_ran": 0, "would_install": 0, "npm_invoked": 0},
    )
    expect(
        "plugin_sessionstart_installs_on_miss",
        plugin_sessionstart_node_modules(0),
        {"session_ran": 1, "would_install": 1, "npm_invoked": 0, "setup_ran": 0},
    )
    expect(
        "plugin_sessionstart_skips_when_present",
        plugin_sessionstart_node_modules(1),
        {"would_install": 0, "npm_invoked": 0},
    )
    expect(
        "plugin_sessionstart_package_json_diff",
        plugin_sessionstart_package_json(0),
        {"would_install": 1, "npm_invoked": 0},
    )
    expect(
        "plugin_sessionstart_package_json_same",
        plugin_sessionstart_package_json(1),
        {"would_install": 0, "npm_invoked": 0},
    )

    print(
        f"network={NETWORK} npm_invoked={NPM_INVOKED} "
        f"claude_invoked={CLAUDE_INVOKED} runtime_version_probe={RUNTIME_VERSION_PROBE}"
    )
    if FAILS:
        print("result=fail")
        for item in FAILS:
            print(item, file=sys.stderr)
        sys.exit(1)
    print("result=pass")


if __name__ == "__main__":
    main()
