#!/usr/bin/env python3
"""本地夹具：CwdChanged 拦不住已经发生的换目录，环境写进 CLAUDE_ENV_FILE。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不跑 direnv / nix /
devbox，不 cd 进用户目录，也不改本进程以外的 shell 环境。Bash 预执行只在
子进程里 source 夹具自己的临时文件。监视的文件在临时目录里。

这不是 settings 里的 hook，也不是 Claude Code 运行时。

输入输出按 2026-11-22 08:32（Asia/Shanghai）打开的 Hooks reference
（hooks.md）里的 CwdChanged、FileChanged、DirectoryAdded、Persist
environment variables、matcher 表、退出码表、Decision control、类型名单，
以及 hooks-guide 的「Reload environment when directory or files change」
和 changelog 页首，在本地走一遍。

页上没写成可执行结果的格子 simulated=0，不算裁决：
EnterWorktree 会不会让 CwdChanged 开火、子代理里的 cd、带 `.` 的
FileChanged matcher 过滤时到底匹配哪些 basename、watchPaths 写在 JSON
的哪一层、配了 prompt / agent 是跳过还是报错、钩子并行时 `>` 会不会互盖。
"""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path

# 参考页：CwdChanged 单独成行，no matcher support。
# 指南把 CwdChanged 写进 UserPromptSubmit 那一行。两页都是每次都开火。
REFERENCE_CWD_MATCHER_ROW = "own"
GUIDE_CWD_MATCHER_ROW = "merged_with_userpromptsubmit"

# 类型名单：command、http、mcp_tool。没有 prompt、agent。官方示例是 command。
SUPPORTED_TYPES = frozenset({"command", "http", "mcp_tool"})
UNSUPPORTED_TYPES = frozenset({"prompt", "agent"})

# FileChanged / StopFailure 的精确匹配字符集比总表更窄。
FILECHANGED_EXACT = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_|")

EXAMPLE_OLD = "/Users/my-project"
EXAMPLE_NEW = "/Users/my-project/src"

FAILS: list[str] = []


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


def bash_source(env_file: Path, names: list[str]) -> dict[str, str]:
    """子进程里 source 环境文件，再打印指定变量。不碰父进程环境。"""
    parts = []
    for name in names:
        parts.append(f'printf %s "${{{name}}}"')
        parts.append("printf '\\n'")
    script = f"source {shlex.quote(str(env_file))}; " + "; ".join(parts)
    proc = subprocess.run(
        ["bash", "-c", script],
        cwd=env_file.parent,
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)
    lines = proc.stdout.split("\n")
    # 最后一个 printf 的换行会多出一个空元素
    values = lines[: len(names)]
    return dict(zip(names, values))


class EnvFile:
    """CLAUDE_ENV_FILE 的临时文件。CwdChanged 开始时先清掉旧内容。"""

    def __init__(self, directory: Path) -> None:
        self.path = directory / "claude_env_file"
        self.path.write_text("")

    def clear(self) -> None:
        self.path.write_text("")

    def write_line(self, line: str, mode: str) -> None:
        text = line if line.endswith("\n") else line + "\n"
        if mode == ">":
            self.path.write_text(text)
        elif mode == ">>":
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(text)
        else:
            raise ValueError(mode)

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")


def powershell_marker(text: str) -> str:
    """只认专项点名的三类非普通赋值。不实现 PowerShell 解析器。

    三类：未转义的 $PATH、source、direnv 打出来的 $'...' 。
    文件里没有这三类时，记成 plain_copy_stated：页上说普通赋值会被拷进
    PowerShell，本夹具没有执行 PowerShell。
    """
    if "$'" in text or "$PATH" in text or text.lstrip().startswith("source ") or "\nsource " in "\n" + text:
        return "none"
    return "plain_copy_stated"


def begin_cwd_changed(env_file: EnvFile) -> None:
    """下一次 CwdChanged 清掉旧变量。夹具的读法是先把文件截空，再让钩子写。"""
    env_file.clear()


def literal_watch_names(matcher: str | None) -> list[str]:
    """建名单：按 | 切开，每段是字面文件名。省略 matcher 什么都不加。"""
    if matcher is None:
        return []
    return matcher.split("|")


def filter_path(matcher: str | None) -> str:
    """过滤哪一组钩子跑。不计算正则到底匹配谁。"""
    if matcher is None:
        return "omitted"
    if matcher == "*":
        return "star"
    if all(ch in FILECHANGED_EXACT for ch in matcher):
        return "exact"
    return "regex"


def group_runs(matcher: str | None, basename: str) -> str:
    """返回 yes / no / not_deduced。regex 路径不推演匹配结果。"""
    kind = filter_path(matcher)
    if kind == "omitted":
        return "yes"
    if kind == "star":
        return "yes"
    if kind == "exact":
        return "yes" if basename in literal_watch_names(matcher) else "no"
    return "not_deduced"


class Watch:
    """matcher 路径始终保留。watchPaths 替换动态名单。"""

    def __init__(self) -> None:
        self.matcher_paths: list[str] = []
        self.dynamic: list[str] = []
        self.seeded = False

    def add_matcher(self, cwd: str, matcher: str | None) -> None:
        for name in literal_watch_names(matcher):
            self.matcher_paths.append(os.path.join(cwd, name))
            self.seeded = True

    def set_watch_paths(self, paths: list[str]) -> None:
        # 替换，不是追加。空数组清掉动态名单。
        self.dynamic = list(paths)
        self.seeded = True

    def effective(self) -> list[str]:
        return list(self.matcher_paths) + list(self.dynamic)

    def started(self) -> bool:
        return bool(self.effective())


def hook_has_env_file(shell: str, windows_no_git_bash: bool) -> int:
    """以 PowerShell 跑的钩子没有 CLAUDE_ENV_FILE。"""
    if shell == "powershell" or windows_no_git_bash:
        return 0
    return 1


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cwdchanged-fixture-") as tmp:
        root = Path(tmp)
        env_file = EnvFile(root)
        run_all(root, env_file)
    if FAILS:
        for item in FAILS:
            print(f"FAIL {item}")
        print("result=fail")
        raise SystemExit(1)
    print("result=pass")


def run_all(root: Path, env_file: EnvFile) -> None:
    case_input_cwd_matches_example()
    case_bash_preamble(env_file)
    case_next_cwd_clears(env_file)
    case_append_and_overwrite_stay_separate(env_file)
    case_exit2_and_json_do_not_block(root)
    case_matcher_ignored()
    case_literal_watch_list()
    case_star_and_omitted(root)
    case_events_via_omitted(root)
    case_filechanged_cannot_block(root)
    case_watchpaths_replace(root)
    case_watcher_needs_a_name(root)
    case_rewrite_retriggers_once(root)
    case_directory_added_boundary()
    case_sessionstart_then_cwdchanged(env_file)
    case_filechanged_env_until_next_cwd(env_file)
    case_powershell_markers(env_file)
    case_hook_shell_powershell()
    case_onfailure_maps_to_exit2()
    case_types_and_unread()
    case_versions()


def case_input_cwd_matches_example() -> None:
    payload = {
        "session_id": "abc123",
        "transcript_path": "/Users/.../.claude/projects/.../transcript.jsonl",
        "cwd": EXAMPLE_NEW,
        "hook_event_name": "CwdChanged",
        "old_cwd": EXAMPLE_OLD,
        "new_cwd": EXAMPLE_NEW,
    }
    expect(
        "cwd_input_example",
        {
            "has_old": int("old_cwd" in payload),
            "has_new": int("new_cwd" in payload),
            "cwd_equals_new": int(payload["cwd"] == payload["new_cwd"]),
            "cwd_still_old": int(payload["cwd"] == payload["old_cwd"]),
            "trigger": "main_conversation_shell",
        },
        {
            "has_old": 1,
            "has_new": 1,
            "cwd_equals_new": 1,
            "cwd_still_old": 0,
            "trigger": "main_conversation_shell",
        },
    )


def case_bash_preamble(env_file: EnvFile) -> None:
    begin_cwd_changed(env_file)
    env_file.write_line("export APP_ENV=src", ">>")
    seen = bash_source(env_file.path, ["APP_ENV"])
    marker = powershell_marker(env_file.text())
    expect(
        "bash_preamble",
        {
            "bash_sees": seen["APP_ENV"],
            "powershell_executed": 0,
            "powershell_marker": marker,
            "direnv_executed": 0,
        },
        {
            "bash_sees": "src",
            "powershell_executed": 0,
            "powershell_marker": "plain_copy_stated",
            "direnv_executed": 0,
        },
    )


def case_next_cwd_clears(env_file: EnvFile) -> None:
    begin_cwd_changed(env_file)
    env_file.write_line("export OLD_DIR=one", ">>")
    before = bash_source(env_file.path, ["OLD_DIR", "NEW_DIR"])
    begin_cwd_changed(env_file)
    after_clear = bash_source(env_file.path, ["OLD_DIR", "NEW_DIR"])
    env_file.write_line("export NEW_DIR=two", ">>")
    after_write = bash_source(env_file.path, ["OLD_DIR", "NEW_DIR"])
    expect(
        "next_cwd_clears",
        {
            "before_old": before["OLD_DIR"],
            "after_clear_old": after_clear["OLD_DIR"],
            "after_write_old": after_write["OLD_DIR"],
            "after_write_new": after_write["NEW_DIR"],
            "old_remains": int(after_write["OLD_DIR"] != ""),
            "clear_order": "truncate_then_hook",
        },
        {
            "before_old": "one",
            "after_clear_old": "",
            "after_write_old": "",
            "after_write_new": "two",
            "old_remains": 0,
            "clear_order": "truncate_then_hook",
        },
    )


def case_append_and_overwrite_stay_separate(env_file: EnvFile) -> None:
    begin_cwd_changed(env_file)
    env_file.write_line("export A=1", ">>")
    env_file.write_line("export B=2", ">>")
    appended = bash_source(env_file.path, ["A", "B"])
    begin_cwd_changed(env_file)
    env_file.write_line("export A=1", ">")
    env_file.write_line("export B=2", ">")
    overwritten = bash_source(env_file.path, ["A", "B"])
    expect(
        "append_vs_overwrite",
        {
            "append_a": appended["A"],
            "append_b": appended["B"],
            "overwrite_a": overwritten["A"],
            "overwrite_b": overwritten["B"],
            "merged_rule": 0,
            "parallel_race": "unread",
            "parallel_simulated": 0,
        },
        {
            "append_a": "1",
            "append_b": "2",
            "overwrite_a": "",
            "overwrite_b": "2",
            "merged_rule": 0,
            "parallel_race": "unread",
            "parallel_simulated": 0,
        },
    )


def case_exit2_and_json_do_not_block(root: Path) -> None:
    # 换目录已经发生。钩子看到的 cwd 就是 new_cwd。
    cwd = EXAMPLE_NEW
    exit_code = 2
    blocked = 0
    payload = {
        "decision": "block",
        "continue": False,
        "systemMessage": "entered src",
        "watchPaths": [str(root / "extra.env")],
    }
    watch = Watch()
    # 读 watchPaths 和 systemMessage。continue 丢掉。decision 没有控制权。
    continue_applied = 0
    decision_applied = 0
    if "watchPaths" in payload:
        watch.set_watch_paths(payload["watchPaths"])
    system_message_read = int("systemMessage" in payload and bool(payload["systemMessage"]))
    expect(
        "no_decision_control",
        {
            "cwd": cwd,
            "cwd_equals_new": int(cwd == EXAMPLE_NEW),
            "exit2_blocked": blocked,
            "can_block": 0,
            "stderr_to": "user",
            "continue_discarded": 1,
            "continue_applied": continue_applied,
            "decision_applied": decision_applied,
            "system_message_read": system_message_read,
            "system_message_to": "terminal_notification",
            "system_message_sdk": 0,
            "watchpaths_read": int(payload["watchPaths"][0] in watch.effective()),
            "exit_code_recorded": exit_code,
        },
        {
            "cwd": EXAMPLE_NEW,
            "cwd_equals_new": 1,
            "exit2_blocked": 0,
            "can_block": 0,
            "stderr_to": "user",
            "continue_discarded": 1,
            "continue_applied": 0,
            "decision_applied": 0,
            "system_message_read": 1,
            "system_message_to": "terminal_notification",
            "system_message_sdk": 0,
            "watchpaths_read": 1,
            "exit_code_recorded": 2,
        },
    )


def case_matcher_ignored() -> None:
    configured = "feature-auth"
    fires = 0
    for _new in (EXAMPLE_NEW, "/Users/my-project/pkg"):
        # 不支持 matcher。写了也被静默忽略，每次换目录都开火。
        _ = configured
        fires += 1
    expect(
        "cwd_no_matcher",
        {
            "reference_row": REFERENCE_CWD_MATCHER_ROW,
            "guide_row": GUIDE_CWD_MATCHER_ROW,
            "silently_ignored": 1,
            "fires": fires,
            "third_table": 0,
        },
        {
            "reference_row": "own",
            "guide_row": "merged_with_userpromptsubmit",
            "silently_ignored": 1,
            "fires": 2,
            "third_table": 0,
        },
    )


def case_literal_watch_list() -> None:
    pair = literal_watch_names(".envrc|.env")
    caret = literal_watch_names(r"^\.env")
    hyphen = literal_watch_names("foo-bar")
    environment_named = ".environment"
    expect(
        "literal_watch_list",
        {
            "pair": ",".join(pair),
            "caret_name": caret[0],
            "caret_is_prefix": int(environment_named in caret or any(environment_named.startswith(n) and n != environment_named for n in caret)),
            "environment_on_list": int(environment_named in caret),
            "hyphen_watch_name": hyphen[0],
            "hyphen_filter": filter_path("foo-bar"),
            "pair_filter": filter_path(".envrc|.env"),
            "pair_filter_outcome": "not_deduced",
            "exact_sample": filter_path("envrc|dotenv"),
        },
        {
            "pair": ".envrc,.env",
            "caret_name": r"^\.env",
            "caret_is_prefix": 0,
            "environment_on_list": 0,
            "hyphen_watch_name": "foo-bar",
            "hyphen_filter": "regex",
            "pair_filter": "regex",
            "pair_filter_outcome": "not_deduced",
            "exact_sample": "exact",
        },
    )


def case_star_and_omitted(root: Path) -> None:
    cwd = str(root / "proj")
    os.makedirs(cwd, exist_ok=True)
    star = Watch()
    star.add_matcher(cwd, "*")
    omitted = Watch()
    omitted.add_matcher(cwd, None)
    both = Watch()
    both.add_matcher(cwd, "envrc")
    both.add_matcher(cwd, None)
    both.add_matcher(cwd, "*")
    envrc = os.path.join(cwd, "envrc")
    star_file = os.path.join(cwd, "*")
    expect(
        "star_vs_omitted",
        {
            "star_watch": os.path.basename(star.matcher_paths[0]),
            "star_is_glob": 0,
            "omitted_adds": len(omitted.matcher_paths),
            "omitted_started": int(omitted.started()),
            "star_started": int(star.started()),
            "envrc_on_both": int(envrc in both.effective()),
            "star_on_both": int(star_file in both.effective()),
            "omitted_runs_on_envrc": group_runs(None, "envrc"),
            "star_runs_on_envrc": group_runs("*", "envrc"),
            "exact_runs_on_envrc": group_runs("envrc|dotenv", "envrc"),
            "exact_runs_on_other": group_runs("envrc|dotenv", "other"),
        },
        {
            "star_watch": "*",
            "star_is_glob": 0,
            "omitted_adds": 0,
            "omitted_started": 0,
            "star_started": 1,
            "envrc_on_both": 1,
            "star_on_both": 1,
            "omitted_runs_on_envrc": "yes",
            "star_runs_on_envrc": "yes",
            "exact_runs_on_envrc": "yes",
            "exact_runs_on_other": "no",
        },
    )


def case_events_via_omitted(root: Path) -> None:
    """播种用 watchPaths。省略 matcher 的那一组匹配所有已监视文件。

    不靠带 `.` 的正则去猜哪一组该跑。
    """
    watched = str(root / "proj" / ".envrc")
    watch = Watch()
    watch.set_watch_paths([watched])
    delivered = []
    for event in ("change", "add", "unlink"):
        if watch.started() and watched in watch.effective() and group_runs(None, os.path.basename(watched)) == "yes":
            delivered.append(event)
    expect(
        "file_events",
        {
            "delivered": ",".join(delivered),
            "matcher": "omitted",
            "regex_used": 0,
        },
        {
            "delivered": "change,add,unlink",
            "matcher": "omitted",
            "regex_used": 0,
        },
    )


def case_filechanged_cannot_block(root: Path) -> None:
    target = root / "data.csv"
    target.write_text("a\n", encoding="utf-8")
    # 文件已经改过。钩子拦不住。
    target.write_text("a\nb\n", encoding="utf-8")
    payload = {"continue": False, "decision": "block", "systemMessage": "file changed"}
    expect(
        "filechanged_no_block",
        {
            "file_has_new_line": int("b" in target.read_text(encoding="utf-8")),
            "blocked": 0,
            "can_block": 0,
            "exit2_stderr_to": "user",
            "continue_discarded": 1,
            "continue_applied": 0,
            "decision_applied": 0,
            "system_message_read": 1,
            "system_message_to": "terminal_notification",
            "system_message_sdk": 0,
            "detector": "filesystem_watcher",
            "ignored_payload_continue": int(payload["continue"] is False),
        },
        {
            "file_has_new_line": 1,
            "blocked": 0,
            "can_block": 0,
            "exit2_stderr_to": "user",
            "continue_discarded": 1,
            "continue_applied": 0,
            "decision_applied": 0,
            "system_message_read": 1,
            "system_message_to": "terminal_notification",
            "system_message_sdk": 0,
            "detector": "filesystem_watcher",
            "ignored_payload_continue": 1,
        },
    )


def case_watchpaths_replace(root: Path) -> None:
    cwd = str(root / "proj")
    watch = Watch()
    watch.add_matcher(cwd, "envrc")
    matcher_path = os.path.join(cwd, "envrc")
    watch.set_watch_paths([str(root / "a"), str(root / "b")])
    after_first = list(watch.effective())
    watch.set_watch_paths([str(root / "c")])
    after_replace = list(watch.effective())
    watch.set_watch_paths([])
    after_empty = list(watch.effective())
    expect(
        "watchpaths_replace",
        {
            "first_has_a": int(str(root / "a") in after_first),
            "first_has_b": int(str(root / "b") in after_first),
            "replace_has_a": int(str(root / "a") in after_replace),
            "replace_has_c": int(str(root / "c") in after_replace),
            "append": 0,
            "empty_has_c": int(str(root / "c") in after_empty),
            "matcher_kept": int(matcher_path in after_empty),
            "dynamic_left": int(any(item != matcher_path for item in after_empty)),
        },
        {
            "first_has_a": 1,
            "first_has_b": 1,
            "replace_has_a": 0,
            "replace_has_c": 1,
            "append": 0,
            "empty_has_c": 0,
            "matcher_kept": 1,
            "dynamic_left": 0,
        },
    )


def case_watcher_needs_a_name(root: Path) -> None:
    cwd = str(root / "proj")
    bare = Watch()
    omitted_only = Watch()
    omitted_only.add_matcher(cwd, None)
    named = Watch()
    named.add_matcher(cwd, "envrc")
    from_cwd = Watch()
    from_cwd.set_watch_paths([str(root / "from-cwd")])
    from_session = Watch()
    from_session.set_watch_paths([str(root / "from-session")])
    # SessionStart 播下的路径，夹具放进同一份动态名单。
    # 随后 CwdChanged 返回 []。这是「播种」和「空数组清掉动态名单」接在一份名单上。
    from_session.set_watch_paths([])
    change_delivered_when_bare = int(bare.started())
    expect(
        "watcher_seed",
        {
            "bare_started": int(bare.started()),
            "omitted_only_started": int(omitted_only.started()),
            "named_started": int(named.started()),
            "cwd_watchpaths_started": int(from_cwd.started()),
            "session_seed_then_empty_dynamic": len(from_session.dynamic),
            "session_seed_join": "seed_is_dynamic",
            "bare_change_delivered": change_delivered_when_bare,
            "retarget_on_cd": "unread",
            "retarget_simulated": 0,
        },
        {
            "bare_started": 0,
            "omitted_only_started": 0,
            "named_started": 1,
            "cwd_watchpaths_started": 1,
            "session_seed_then_empty_dynamic": 0,
            "session_seed_join": "seed_is_dynamic",
            "bare_change_delivered": 0,
            "retarget_on_cd": "unread",
            "retarget_simulated": 0,
        },
    )


def case_rewrite_retriggers_once(root: Path) -> None:
    target = root / "watched.txt"
    target.write_text("raw\n", encoding="utf-8")
    fires = 0
    retriggers = 0
    cap = 1

    def hook() -> None:
        nonlocal retriggers
        # 无条件改写。监视器会再开火。夹具只允许再进一次，然后停。
        target.write_text(target.read_text(encoding="utf-8") + "rewritten\n", encoding="utf-8")
        retriggers += 1
        if retriggers <= cap:
            deliver()

    def deliver() -> None:
        nonlocal fires
        fires += 1
        if fires > cap + 1:
            raise RuntimeError("unterminated rewrite loop")
        if fires == 1:
            hook()

    deliver()
    expect(
        "rewrite_retriggers",
        {
            "fires": fires,
            "retriggers": retriggers,
            "stopped_by": "cap",
            "infinite": 0,
            "rewritten": int("rewritten" in target.read_text(encoding="utf-8")),
        },
        {
            "fires": 2,
            "retriggers": 1,
            "stopped_by": "cap",
            "infinite": 0,
            "rewritten": 1,
        },
    )


def directory_added(kind: str, matcher: str | None) -> dict:
    """DirectoryAdded 是边界。添加已经完成，钩子拦不住。"""
    no_fire = {"startup_flag", "permissions_tab", "already_working", "inside_working"}
    if kind in no_fire:
        covered = "SessionStart" if kind == "startup_flag" else ""
        return {
            "fires": 0,
            "covered_by": covered,
            "blocked": 0,
            "already_added": 0,
            "stderr_to": "",
            "system_message_to": "",
            "waited": 0,
        }
    source = kind
    if matcher is not None and matcher != source:
        return {
            "fires": 0,
            "covered_by": "",
            "blocked": 0,
            "already_added": 1,
            "stderr_to": "",
            "system_message_to": "",
            "waited": 0,
        }
    if source == "slash_command":
        message_to = "claude_next_turn"
    elif source == "register_repo_root":
        message_to = "debug_log"
    else:
        message_to = ""
    return {
        "fires": 1,
        "covered_by": "",
        "blocked": 0,
        "already_added": 1,
        "stderr_to": "debug_log",
        "system_message_to": message_to,
        "waited": 0,
    }


def case_directory_added_boundary() -> None:
    startup = directory_added("startup_flag", None)
    tab = directory_added("permissions_tab", None)
    already = directory_added("already_working", None)
    inside = directory_added("inside_working", None)
    slash = directory_added("slash_command", "slash_command")
    sdk = directory_added("register_repo_root", None)
    mismatch = directory_added("register_repo_root", "slash_command")
    expect(
        "directory_added_boundary",
        {
            "startup_fires": startup["fires"],
            "startup_covered_by": startup["covered_by"],
            "tab_fires": tab["fires"],
            "already_fires": already["fires"],
            "inside_fires": inside["fires"],
            "slash_fires": slash["fires"],
            "slash_blocked": slash["blocked"],
            "slash_already_added": slash["already_added"],
            "slash_stderr_to": slash["stderr_to"],
            "slash_message_to": slash["system_message_to"],
            "slash_continue_discarded": 1,
            "sdk_fires": sdk["fires"],
            "sdk_blocked": sdk["blocked"],
            "sdk_message_to": sdk["system_message_to"],
            "sdk_failure_to": "debug_log",
            "mismatch_fires": mismatch["fires"],
            "waited": slash["waited"],
            "timeout_default": 600,
            "same_stderr_row_as_cwd": 0,
        },
        {
            "startup_fires": 0,
            "startup_covered_by": "SessionStart",
            "tab_fires": 0,
            "already_fires": 0,
            "inside_fires": 0,
            "slash_fires": 1,
            "slash_blocked": 0,
            "slash_already_added": 1,
            "slash_stderr_to": "debug_log",
            "slash_message_to": "claude_next_turn",
            "slash_continue_discarded": 1,
            "sdk_fires": 1,
            "sdk_blocked": 0,
            "sdk_message_to": "debug_log",
            "sdk_failure_to": "debug_log",
            "mismatch_fires": 0,
            "waited": 0,
            "timeout_default": 600,
            "same_stderr_row_as_cwd": 0,
        },
    )


def case_sessionstart_then_cwdchanged(env_file: EnvFile) -> None:
    """指南的配对：SessionStart 和 CwdChanged 都往 CLAUDE_ENV_FILE 写。

    不跑 direnv。重定向用指南示例的 `>`。持久化那一节的 `>>` 在另一格。
    """
    env_file.write_line("export APP_ENV=launch", ">")
    launched = bash_source(env_file.path, ["APP_ENV"])
    begin_cwd_changed(env_file)
    cleared = bash_source(env_file.path, ["APP_ENV"])
    env_file.write_line("export APP_ENV=src", ">")
    moved = bash_source(env_file.path, ["APP_ENV"])
    expect(
        "sessionstart_and_cwdchanged",
        {
            "launch": launched["APP_ENV"],
            "after_clear": cleared["APP_ENV"],
            "after_cd": moved["APP_ENV"],
            "direnv_executed": 0,
            "redirect": ">",
        },
        {
            "launch": "launch",
            "after_clear": "",
            "after_cd": "src",
            "direnv_executed": 0,
            "redirect": ">",
        },
    )


def case_filechanged_env_until_next_cwd(env_file: EnvFile) -> None:
    begin_cwd_changed(env_file)
    env_file.write_line("export FILE_REV=1", ">>")
    before = bash_source(env_file.path, ["FILE_REV"])
    # FileChanged 不再清。下一次 CwdChanged 才清。
    held = bash_source(env_file.path, ["FILE_REV"])
    begin_cwd_changed(env_file)
    after = bash_source(env_file.path, ["FILE_REV"])
    expect(
        "filechanged_env_cleared_on_cwd",
        {
            "before": before["FILE_REV"],
            "held_across_filechanged": held["FILE_REV"],
            "after_next_cwd": after["FILE_REV"],
        },
        {
            "before": "1",
            "held_across_filechanged": "1",
            "after_next_cwd": "",
        },
    )


def case_powershell_markers(env_file: EnvFile) -> None:
    begin_cwd_changed(env_file)
    env_file.write_line("export FOO=$'bar'", ">")
    env_file.write_line('export PATH="$PATH:./node_modules/.bin"', ">>")
    seen = bash_source(env_file.path, ["FOO", "PATH"])
    marker = powershell_marker(env_file.text())
    expect(
        "powershell_markers",
        {
            "bash_foo": seen["FOO"],
            "bash_path_has_suffix": int(seen["PATH"].endswith("./node_modules/.bin")),
            "powershell_receives": marker,
            "powershell_executed": 0,
            "sandboxed_powershell_receives": "none",
            "debug_line": "Session environment is not all plain assignments",
            "parser_invented": 0,
            "windows_executed": 0,
        },
        {
            "bash_foo": "bar",
            "bash_path_has_suffix": 1,
            "powershell_receives": "none",
            "powershell_executed": 0,
            "sandboxed_powershell_receives": "none",
            "debug_line": "Session environment is not all plain assignments",
            "parser_invented": 0,
            "windows_executed": 0,
        },
    )


def case_hook_shell_powershell() -> None:
    expect(
        "hook_shell_powershell",
        {
            "bash_hook_has_file": hook_has_env_file("bash", False),
            "powershell_hook_has_file": hook_has_env_file("powershell", False),
            "windows_default_has_file": hook_has_env_file("bash", True),
            "available_on": "SessionStart,Setup,CwdChanged,FileChanged",
        },
        {
            "bash_hook_has_file": 1,
            "powershell_hook_has_file": 0,
            "windows_default_has_file": 0,
            "available_on": "SessionStart,Setup,CwdChanged,FileChanged",
        },
    )


def case_onfailure_maps_to_exit2() -> None:
    # onFailure block 去做这一事件的 exit 2 会做的事。这只事件的 exit 2 不拦。
    cwd = EXAMPLE_NEW
    expect(
        "onfailure_block",
        {
            "maps_to": "exit2",
            "blocked": 0,
            "cwd_equals_new": int(cwd == EXAMPLE_NEW),
            "stderr_to": "user",
            "permissionrequest_exception_copied": 0,
        },
        {
            "maps_to": "exit2",
            "blocked": 0,
            "cwd_equals_new": 1,
            "stderr_to": "user",
            "permissionrequest_exception_copied": 0,
        },
    )


def case_types_and_unread() -> None:
    expect(
        "types_and_unread",
        {
            "supported": ",".join(sorted(SUPPORTED_TYPES)),
            "prompt_supported": int("prompt" in SUPPORTED_TYPES),
            "agent_supported": int("agent" in SUPPORTED_TYPES),
            "example_type": "command",
            "prompt_outcome": "unread",
            "prompt_simulated": 0,
            "enterworktree_fires": "unread",
            "enterworktree_simulated": 0,
            "subagent_cd_fires": "unread",
            "subagent_cd_simulated": 0,
            "watchpaths_json_level": "unread",
            "watchpaths_level_simulated": 0,
        },
        {
            "supported": "command,http,mcp_tool",
            "prompt_supported": 0,
            "agent_supported": 0,
            "example_type": "command",
            "prompt_outcome": "unread",
            "prompt_simulated": 0,
            "enterworktree_fires": "unread",
            "enterworktree_simulated": 0,
            "subagent_cd_fires": "unread",
            "subagent_cd_simulated": 0,
            "watchpaths_json_level": "unread",
            "watchpaths_level_simulated": 0,
        },
    )


def case_versions() -> None:
    expect(
        "versions",
        {
            "latest": "2.1.330",
            "cwd_mention_in_330": 0,
            "fullscreen_fix": "2.1.327",
            "events_added": "2.1.83",
            "directory_added_added": "2.1.219",
            "start_dir_in_330": 1,
            "start_dir_linked": 0,
            "powershell_env_since": "2.1.296",
        },
        {
            "latest": "2.1.330",
            "cwd_mention_in_330": 0,
            "fullscreen_fix": "2.1.327",
            "events_added": "2.1.83",
            "directory_added_added": "2.1.219",
            "start_dir_in_330": 1,
            "start_dir_linked": 0,
            "powershell_env_since": "2.1.296",
        },
    )


if __name__ == "__main__":
    main()
