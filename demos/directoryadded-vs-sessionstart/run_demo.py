#!/usr/bin/env python3
"""本地夹具：启动 --add-dir 归 SessionStart，中途 /add-dir 才是 DirectoryAdded。

按 2026-11-28 08:32（Asia/Shanghai）打开的 Hooks reference（hooks.md）里
DirectoryAdded 专节、matcher 表、退出码表、Decision control 总表、
Persist environment variables 的 NOTE、timeout 默认值，
cli-reference 的 --add-dir，以及 permissions 的 Working directories
与「Additional directories grant file access, not configuration」，在本地走一遍。

不调用 API，不访问网络，不启动 Claude Code，不读密钥，不装依赖。
这不是 settings 里的 hook，也不是 Claude Code 运行时。

页上没有把 DirectoryAdded 和 "async": true 等同起来。夹具不套用
「异步钩子不再强制 timeout」。timeout_default=600 只记录专项写的默认值。
async_true_equated=0。

「SessionStart covers those directories」那句的主语是启动旗标。
settings 的 additionalDirectories 不在开火句里，也不在三条 doesn't fire 名单里。
夹具按开火句记 directory_added=0，covers_sentence=0。
"""

from __future__ import annotations

import shlex
import subprocess
import tempfile
from pathlib import Path

PRIMARY = "/Users/my-project"
ENV_FILE_EVENTS = frozenset({"SessionStart", "Setup", "CwdChanged", "FileChanged"})
TIMEOUT_DEFAULT = 600

FAILS: list[str] = []
NETWORK = 0
CLAUDE_INVOKED = 0
RUNTIME_VERSION_PROBE = 0

EXAMPLE_INPUT = {
    "session_id": "abc123",
    "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
    "cwd": "/Users/my-project",
    "hook_event_name": "DirectoryAdded",
    "directory": "/Users/my-other-repo",
    "source": "slash_command",
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


def fresh_working() -> set[str]:
    return {PRIMARY}


def inside_parent(path: str, working: set[str]) -> str | None:
    """路径严格位于某个已有工作目录内部。同名目录不算内部。"""
    for root in working:
        prefix = root.rstrip("/") + "/"
        if path.startswith(prefix):
            return root
    return None


def matcher_matches(matcher: str | None, source: str) -> bool:
    """省略、空串和 * 匹配该事件的每一次。其余只做页上两枚精确值。"""
    if matcher is None or matcher in ("", "*"):
        return True
    parts: list[str] = []
    for chunk in matcher.split("|"):
        for piece in chunk.split(","):
            piece = piece.strip()
            if piece:
                parts.append(piece)
    return source in parts


def apply_directory_added(
    working: set[str],
    directory: str,
    source: str,
    stdout: dict | None,
    exit_code: int,
    stderr: str,
) -> dict:
    """目录先进入集合，再读钩子输出。continue 丢掉。exit 2 的 stderr 进 debug_log。"""
    working.add(directory)
    discarded: list[str] = []
    system_message = ""
    decision_applied = 0
    if isinstance(stdout, dict):
        if "continue" in stdout:
            discarded.append("continue")
        if "decision" in stdout:
            decision_applied = 0
        system_message = str(stdout.get("systemMessage") or "")
    debug_log: list[str] = []
    next_turn = ""
    transcript_failed = 0
    if source == "slash_command":
        if system_message:
            next_turn = system_message
        if exit_code == 2:
            transcript_failed = 1
            if stderr:
                debug_log.append(stderr)
    elif source == "register_repo_root":
        if system_message:
            debug_log.append(system_message)
        if exit_code == 2 and stderr:
            debug_log.append(stderr)
    if system_message and source == "slash_command":
        system_message_to = "next_turn"
    elif system_message and source == "register_repo_root":
        system_message_to = "debug_log"
    else:
        system_message_to = "none"
    return {
        "blocked": 0,
        "still_added": 1 if directory in working else 0,
        "background": 1,
        "added_before_hook": 1,
        "continue_applied": 0,
        "decision_applied": decision_applied,
        "discarded": ",".join(discarded),
        "user_notice": 0,
        "next_turn": 1 if next_turn else 0,
        "system_message_to": system_message_to,
        "stderr_to": "debug_log" if exit_code == 2 else "none",
        "transcript_failed": transcript_failed,
        "debug_has_stderr": 1 if stderr and stderr in debug_log else 0,
        "debug_has_system": 1 if system_message and system_message in debug_log else 0,
        "timeout_default": TIMEOUT_DEFAULT,
        "async_true_equated": 0,
    }


def no_fire(reason: str) -> dict:
    return {
        "directory_added": 0,
        "event_fired": 0,
        "hook_ran": 0,
        "session_start": 0,
        "blocked": 0,
        "reason": reason,
    }


def startup_add_dir(paths: list[str], passed_as: str = "--add-dir") -> dict:
    """启动旗标先进入工作目录集合。SessionStart 覆盖。DirectoryAdded 不开火。"""
    working = fresh_working()
    for path in paths:
        working.add(path)
    missing = [path for path in paths if path not in working]
    return {
        "session_start": 1,
        "directory_added": 0,
        "event_fired": 0,
        "passed_as": passed_as,
        "covers_sentence": 1,
        "in_working": 0 if missing else 1,
        "blocked": 0,
        "register_repo_root": 0,
    }


def sdk_launch(option: str) -> dict:
    """TypeScript additionalDirectories 与 Python add_dirs 作为 --add-dir 传入。"""
    row = startup_add_dir(["/Users/sdk-repo"])
    row["option"] = option
    return row


def settings_additional(paths: list[str]) -> dict:
    """持久项不在 DirectoryAdded 的开火句里。covers 那句不安到这把钥匙上。"""
    return {
        "directory_added": 0,
        "event_fired": 0,
        "in_fire_sentence": 0,
        "in_does_not_fire_list": 0,
        "covers_sentence": 0,
        "file_access_only": 1,
        "config_exceptions": 0,
        "access": 1 if paths else 0,
        "paths": len(paths),
    }


def mid_add(
    working: set[str],
    path: str,
    source: str,
    stdout: dict | None = None,
    exit_code: int = 0,
    stderr: str = "",
    matcher: str | None = None,
    channel: str = "command",
) -> dict:
    """中途添加。Workspace、已是工作目录、位于内部，都不开火。"""
    if channel == "workspace":
        working.add(path)
        row = no_fire("workspace")
        row["in_working"] = 1 if path in working else 0
        row["in_does_not_fire_list"] = 1
        return row
    if path in working:
        row = no_fire("already")
        row["in_working"] = 1
        row["newly_added"] = 0
        row["in_does_not_fire_list"] = 1
        return row
    parent = inside_parent(path, working)
    if parent is not None:
        row = no_fire("inside")
        row["in_does_not_fire_list"] = 1
        row["runtime_tested"] = 0
        if parent == PRIMARY:
            row["permissions_sentence"] = 1
            row["working_directory_added"] = 0
            row["permissions_requires"] = "2.1.257"
        else:
            row["permissions_sentence"] = 0
            row["working_directory_added"] = "not_read"
            row["permissions_requires"] = ""
        return row
    working.add(path)
    if not matcher_matches(matcher, source):
        return {
            "directory_added": 1,
            "event_fired": 1,
            "hook_ran": 0,
            "source": source,
            "blocked": 0,
            "still_added": 1 if path in working else 0,
            "background": 1,
            "added_before_hook": 1,
            "timeout_default": TIMEOUT_DEFAULT,
            "async_true_equated": 0,
            "user_notice": 0,
        }
    out = apply_directory_added(working, path, source, stdout, exit_code, stderr)
    out["directory_added"] = 1
    out["event_fired"] = 1
    out["hook_ran"] = 1
    out["source"] = source
    return out


def later_bash(event: str, official: Path, guessed: Path) -> dict:
    """只 source 资格名单里的 CLAUDE_ENV_FILE。猜测路径不读。"""
    env: dict[str, str] = {}
    if event in ENV_FILE_EVENTS:
        env["CLAUDE_ENV_FILE"] = str(official)
    script = 'printf %s "${SEEDED}"'
    if "CLAUDE_ENV_FILE" in env:
        script = f"source {shlex.quote(env['CLAUDE_ENV_FILE'])}; {script}"
    if str(guessed) in script:
        raise RuntimeError("runtime sourced the guessed path")
    proc = subprocess.run(
        ["bash", "-c", script],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "bash failed")
    seen = proc.stdout
    return {
        "env_var_present": 1 if "CLAUDE_ENV_FILE" in env else 0,
        "runtime_read_guess": 0,
        "guess_written": 1 if guessed.is_file() else 0,
        "bash_sees": seen if seen else "empty",
    }


def env_case(event: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        official = root / "official.sh"
        guessed = root / "guessed.sh"
        official.write_text("export SEEDED=from-start\n")
        guessed.write_text("export SEEDED=from-guess\n")
        return later_bash(event, official, guessed)


def main() -> None:
    example_ok = int(
        EXAMPLE_INPUT["hook_event_name"] == "DirectoryAdded"
        and EXAMPLE_INPUT["source"] == "slash_command"
        and EXAMPLE_INPUT["directory"] == "/Users/my-other-repo"
        and "permission_mode" not in EXAMPLE_INPUT
    )
    expect(
        "example_input",
        {
            "shape": example_ok,
            "permission_mode_required": 0,
            "source": EXAMPLE_INPUT["source"],
        },
        {"shape": 1, "permission_mode_required": 0, "source": "slash_command"},
    )

    expect(
        "startup_add_dir",
        startup_add_dir(["/Users/apps", "/Users/lib"]),
        {
            "session_start": 1,
            "directory_added": 0,
            "event_fired": 0,
            "passed_as": "--add-dir",
            "covers_sentence": 1,
            "in_working": 1,
            "blocked": 0,
        },
    )
    expect(
        "sdk_launch_typescript",
        sdk_launch("typescript_additionalDirectories"),
        {
            "session_start": 1,
            "directory_added": 0,
            "passed_as": "--add-dir",
            "option": "typescript_additionalDirectories",
            "register_repo_root": 0,
            "covers_sentence": 1,
        },
    )
    expect(
        "sdk_launch_python",
        sdk_launch("python_add_dirs"),
        {
            "session_start": 1,
            "directory_added": 0,
            "passed_as": "--add-dir",
            "option": "python_add_dirs",
            "register_repo_root": 0,
        },
    )
    expect(
        "settings_additional_directories",
        settings_additional(["/Users/persisted-repo"]),
        {
            "directory_added": 0,
            "event_fired": 0,
            "in_fire_sentence": 0,
            "in_does_not_fire_list": 0,
            "covers_sentence": 0,
            "file_access_only": 1,
            "config_exceptions": 0,
            "access": 1,
        },
    )

    workspace = mid_add(
        fresh_working(),
        "/Users/from-workspace",
        "slash_command",
        channel="workspace",
    )
    expect(
        "workspace_tab",
        workspace,
        {
            "directory_added": 0,
            "event_fired": 0,
            "hook_ran": 0,
            "in_working": 1,
            "in_does_not_fire_list": 1,
            "reason": "workspace",
        },
    )

    already = mid_add(fresh_working(), PRIMARY, "slash_command")
    expect(
        "already_working",
        already,
        {
            "directory_added": 0,
            "reason": "already",
            "newly_added": 0,
            "in_does_not_fire_list": 1,
        },
    )

    inside_primary = mid_add(
        fresh_working(),
        "/Users/my-project/packages/web",
        "slash_command",
    )
    expect(
        "inside_primary_subdir",
        inside_primary,
        {
            "directory_added": 0,
            "reason": "inside",
            "permissions_sentence": 1,
            "working_directory_added": 0,
            "permissions_requires": "2.1.257",
            "runtime_tested": 0,
        },
    )

    added_parent = fresh_working()
    added_parent.add("/Users/my-other-repo")
    inside_added = mid_add(
        added_parent,
        "/Users/my-other-repo/lib",
        "slash_command",
    )
    expect(
        "inside_added_dir",
        inside_added,
        {
            "directory_added": 0,
            "reason": "inside",
            "permissions_sentence": 0,
            "working_directory_added": "not_read",
            "runtime_tested": 0,
        },
    )

    slash = mid_add(
        fresh_working(),
        "/Users/my-other-repo",
        "slash_command",
        stdout={"continue": False},
        exit_code=0,
    )
    expect(
        "mid_slash_add_dir",
        slash,
        {
            "directory_added": 1,
            "source": "slash_command",
            "hook_ran": 1,
            "blocked": 0,
            "added_before_hook": 1,
            "background": 1,
            "still_added": 1,
            "timeout_default": 600,
            "async_true_equated": 0,
            "continue_applied": 0,
        },
    )

    note = mid_add(
        fresh_working(),
        "/Users/my-other-repo",
        "slash_command",
        stdout={"systemMessage": "prepare-note", "continue": False},
        exit_code=0,
    )
    expect(
        "slash_system_message_next_turn",
        note,
        {
            "source": "slash_command",
            "system_message_to": "next_turn",
            "next_turn": 1,
            "user_notice": 0,
            "debug_has_system": 0,
            "continue_applied": 0,
            "blocked": 0,
        },
    )

    failed = mid_add(
        fresh_working(),
        "/Users/my-other-repo",
        "slash_command",
        stdout={"continue": False, "decision": "block"},
        exit_code=2,
        stderr="install-failed",
    )
    expect(
        "slash_exit_2_debug_log",
        failed,
        {
            "blocked": 0,
            "still_added": 1,
            "stderr_to": "debug_log",
            "debug_has_stderr": 1,
            "transcript_failed": 1,
            "user_notice": 0,
            "continue_applied": 0,
            "decision_applied": 0,
            "discarded": "continue",
        },
    )

    sdk_mid = mid_add(
        fresh_working(),
        "/Users/sdk-mid-repo",
        "register_repo_root",
        stdout={"systemMessage": "prepare-note", "continue": False},
        exit_code=2,
        stderr="install-failed",
    )
    expect(
        "register_repo_root",
        sdk_mid,
        {
            "directory_added": 1,
            "source": "register_repo_root",
            "hook_ran": 1,
            "blocked": 0,
            "added_before_hook": 1,
            "background": 1,
            "still_added": 1,
            "system_message_to": "debug_log",
            "debug_has_system": 1,
            "debug_has_stderr": 1,
            "next_turn": 0,
            "user_notice": 0,
            "transcript_failed": 0,
            "continue_applied": 0,
            "stderr_to": "debug_log",
        },
    )

    skip_sdk = mid_add(
        fresh_working(),
        "/Users/sdk-mid-repo",
        "register_repo_root",
        matcher="slash_command",
    )
    expect(
        "matcher_slash_skips_register",
        skip_sdk,
        {
            "event_fired": 1,
            "hook_ran": 0,
            "source": "register_repo_root",
            "still_added": 1,
            "blocked": 0,
            "added_before_hook": 1,
        },
    )
    skip_slash = mid_add(
        fresh_working(),
        "/Users/my-other-repo",
        "slash_command",
        matcher="register_repo_root",
    )
    expect(
        "matcher_register_skips_slash",
        skip_slash,
        {
            "event_fired": 1,
            "hook_ran": 0,
            "source": "slash_command",
            "still_added": 1,
            "blocked": 0,
        },
    )

    expect(
        "no_env_file",
        env_case("DirectoryAdded"),
        {
            "env_var_present": 0,
            "guess_written": 1,
            "runtime_read_guess": 0,
            "bash_sees": "empty",
        },
    )
    expect(
        "startup_sessionstart_env",
        env_case("SessionStart"),
        {
            "env_var_present": 1,
            "runtime_read_guess": 0,
            "bash_sees": "from-start",
        },
    )

    print(
        f"network={NETWORK} claude_invoked={CLAUDE_INVOKED} "
        f"runtime_version_probe={RUNTIME_VERSION_PROBE}"
    )
    if FAILS:
        print("result=fail")
        for item in FAILS:
            print(item)
        raise SystemExit(1)
    print("result=pass")


if __name__ == "__main__":
    main()
