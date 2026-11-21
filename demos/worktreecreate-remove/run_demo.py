#!/usr/bin/env python3
"""本地夹具：WorktreeCreate 替换默认 git，必须交回路径；WorktreeRemove 只认退出码。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不执行 git worktree、
svn checkout，也不删夹具以外的目录。删除只发生在本脚本建的临时目录里。
这不是 settings 里的 hook。

输入输出按 2026-11-21 打开的 Hooks reference 专项、退出码表、Decision
control、类型名单，以及 worktrees 页里和钩子契约直接相关的句子，在本地走一遍。
mcp_tool 怎么交回路径、配了 prompt / agent 之后是跳过还是报错、多只
WorktreeCreate 谁的路径生效、hookEventName 写错时怎么失败，页上没有写成
可执行的结果。这些格 simulated=0，不算裁决。
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# 参考页合并的 no-matcher 行。CwdChanged 单独成行，不在这一格。
REFERENCE_NO_MATCHER = frozenset(
    {
        "UserPromptSubmit",
        "PostToolBatch",
        "Stop",
        "TeammateIdle",
        "TaskCreated",
        "TaskCompleted",
        "WorktreeCreate",
        "WorktreeRemove",
        "MessageDisplay",
    }
)
# 指南把 CwdChanged 写进了同一行。
GUIDE_NO_MATCHER = REFERENCE_NO_MATCHER | {"CwdChanged"}

# 支持 command、http、mcp_tool。不支持 prompt、agent。Setup 不在这一对里。
SUPPORTED_TYPES = frozenset({"command", "http", "mcp_tool"})
UNSUPPORTED_TYPES = frozenset({"prompt", "agent"})

CREATE_EXAMPLE_KEYS = frozenset(
    {"session_id", "transcript_path", "cwd", "hook_event_name", "name"}
)
REMOVE_EXAMPLE_KEYS = frozenset(
    {"session_id", "transcript_path", "cwd", "hook_event_name", "worktree_path"}
)

EXAMPLE_SESSION = "abc123"
EXAMPLE_TRANSCRIPT = (
    "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl"
)
EXAMPLE_NAME = "feature-auth"
KEPT_PREFIX = "worktree removal failed, kept:"


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def last_nonempty_line(stdout: str) -> str:
    """command hook 的路径：剥掉 ANSI 之后，stdout 最后一行非空。"""
    lines = [line.strip() for line in strip_ansi(stdout).splitlines()]
    kept = [line for line in lines if line]
    if not kept:
        return ""
    return kept[-1]


def symlink_below_repo(path: str, repo_root: str) -> bool:
    """符号链接的位置在仓库根以下。仓库根自己不算 below。"""
    repo = os.path.abspath(repo_root)
    here = os.path.abspath(path)
    if here == repo or not here.startswith(repo + os.sep):
        return False
    return os.path.islink(path)


def classify_path(raw: str, run_dir: str, repo_root: str) -> tuple[str, str, str]:
    """按专项输出那几句走。

    返回 (resolved, fail, rejected)。
    fail 为空表示路径语法通过，并且是可进入的目录。
    绝对路径里的 . / .. 先拒绝，名字就是那段。
    相对路径先按钩子运行目录折叠 . / ..，再看有没有穿过仓库根以下的符号链接。
    解析结果不是可进入的目录时，fail=not_enterable。页上这句写了会话退出码 1。
    没读到绝对路径 .. 和符号链接这两条拒绝的会话退出码，调用方不要补。
    """
    if raw == "":
        return "", "no_path", ""
    if os.path.isabs(raw):
        segments = [part for part in raw.split("/") if part != ""]
        for part in segments:
            if part in (".", ".."):
                return "", "rejected_component", part
        current = "/"
        for part in segments:
            nxt = os.path.join(current, part) if current != "/" else "/" + part
            if symlink_below_repo(nxt, repo_root):
                return "", "rejected_component", part
            current = nxt
        resolved = current
    else:
        current = os.path.abspath(run_dir)
        for part in raw.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                current = os.path.dirname(current)
                continue
            nxt = os.path.join(current, part)
            if symlink_below_repo(nxt, repo_root):
                return "", "rejected_component", part
            current = nxt
        resolved = current
    if not os.path.isdir(resolved) or not os.access(resolved, os.X_OK):
        return resolved, "not_enterable", ""
    return resolved, "", ""


@dataclass
class Layout:
    root: str
    repo: str
    run_dir: str
    launch_root: str

    def worktree(self, name: str) -> str:
        path = os.path.join(self.root, "made", name)
        os.makedirs(path, exist_ok=True)
        return path

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def make_layout() -> Layout:
    root = tempfile.mkdtemp(prefix="wt-hook-fixture-")
    repo = os.path.join(root, "repo")
    os.makedirs(repo)
    os.makedirs(os.path.join(root, "made"))
    return Layout(root=root, repo=repo, run_dir=repo, launch_root=repo)


@dataclass
class Record:
    name: str
    simulated: int = 1
    note: str = "ok"
    flags: dict[str, object] = field(default_factory=dict)

    def line(self) -> str:
        parts = [self.name, f"simulated={self.simulated}", f"note={self.note}"]
        for key, value in self.flags.items():
            parts.append(f"{key}={value}")
        return " ".join(parts)


def rec(name: str, simulated: int = 1, note: str = "ok", **flags: object) -> Record:
    return Record(name=name, simulated=simulated, note=note, flags=dict(flags))


def expect(record: Record, **flags: object) -> None:
    if "simulated" in flags and record.simulated != flags.pop("simulated"):
        raise SystemExit(f"{record.name} simulated: got {record.simulated!r}")
    if "note" in flags and record.note != flags.pop("note"):
        raise SystemExit(f"{record.name} note: got {record.note!r}")
    for key, value in flags.items():
        actual = record.flags[key]
        if actual != value:
            raise SystemExit(f"{record.name} {key}: got {actual!r}, want {value!r}")


def create_example(cwd: str) -> dict[str, str]:
    return {
        "session_id": EXAMPLE_SESSION,
        "transcript_path": EXAMPLE_TRANSCRIPT,
        "cwd": cwd,
        "hook_event_name": "WorktreeCreate",
        "name": EXAMPLE_NAME,
    }


def remove_example(cwd: str, worktree_path: str) -> dict[str, str]:
    return {
        "session_id": EXAMPLE_SESSION,
        "transcript_path": EXAMPLE_TRANSCRIPT,
        "cwd": cwd,
        "hook_event_name": "WorktreeRemove",
        "worktree_path": worktree_path,
    }


def adopt(path: str, *, contained_in_git_repo: bool, git_metadata: bool) -> dict[str, object]:
    """worktrees 页：没有 git 元数据的目录，只有不被任何 git 仓库包住时才通过。

    包在仓库里时，页上写 Claude Code 用 git resolves its working tree to 拒绝，
    目录留在磁盘。这里不跑 git，用夹具旗标表示「被一个仓库包住」。
    """
    if git_metadata:
        return {"adopted": 1, "refused": 0, "dir_left": 1, "reason": "git_metadata"}
    if contained_in_git_repo:
        return {
            "adopted": 0,
            "refused": 1,
            "dir_left": 1,
            "reason": "git_resolves_working_tree",
        }
    return {"adopted": 1, "refused": 0, "dir_left": 1, "reason": "none"}


def settle_create(
    layout: Layout,
    *,
    hook_type: str,
    configured: bool,
    trigger: str,
    hook_where: str,
    flags: tuple[str, ...],
    matcher: str,
    exit_code: int,
    stdout: str,
    http_status: int,
    http_body: dict | None,
    contained_in_git_repo: bool,
    git_metadata: bool,
    copy_env: bool,
    version_before_2_1_300: bool,
) -> dict[str, object]:
    """Create 的结果。没配钩子、不开火的触发、不支持的类型，都不进入路径契约。"""
    fires = 1
    if not configured:
        fires = 0
    if trigger == "bash_git_worktree_add":
        fires = 0
    if hook_where == "plugin" and "--worktree" in flags and "--tmux" in flags:
        fires = 0
    if (
        version_before_2_1_300
        and hook_where == "plugin"
        and "--worktree" in flags
        and "--tmux" not in flags
    ):
        fires = 0
    if hook_type in UNSUPPORTED_TYPES:
        return {
            "fires": 0,
            "supported": 0,
            "outcome_stated": 0,
            "creation_failed": 0,
            "creation_ok": 0,
            "decision_applied": 0,
            "continue_applied": 0,
            "system_message_applied": 0,
            "matcher_applied": 0,
            "include_processed": 0,
            "replaced_default_git": 1 if configured else 0,
        }
    if hook_type == "mcp_tool":
        return {
            "fires": fires,
            "supported": 1,
            "in_supported_set": 1,
            "path_return_stated": 0,
            "outcome_stated": 0,
            "creation_ok": 0,
            "creation_failed": 0,
            "matcher_applied": 0,
            "replaced_default_git": 1 if configured else 0,
        }
    if fires == 0:
        return {
            "fires": 0,
            "supported": 1 if hook_type in SUPPORTED_TYPES else 0,
            "creation_ok": 0,
            "creation_failed": 0,
            "decision_applied": 0,
            "continue_applied": 0,
            "system_message_applied": 0,
            "matcher_applied": 0,
            "include_processed": 0,
            "replaced_default_git": 1 if configured else 0,
            "pretooluse_gate": 1 if trigger == "bash_git_worktree_add" else 0,
            "pretooluse_outcome_simulated": 0,
        }

    decision_applied = 0
    continue_applied = 0
    system_message_applied = 0
    terminal_present = 0
    path_raw = ""
    read_as = ""
    if hook_type == "command":
        path_raw = last_nonempty_line(stdout)
        read_as = "path_line"
        # stdout 就是路径。JSON 不会被当成 decision。
    elif hook_type == "http":
        read_as = "hookSpecificOutput.worktreePath"
        body = http_body or {}
        if "terminalSequence" in body:
            terminal_present = 1
        if http_status < 200 or http_status >= 300:
            return {
                "fires": 1,
                "supported": 1,
                "read_as": read_as,
                "creation_ok": 0,
                "creation_failed": 1,
                "fail": "hook_failed",
                "session_exit_stated": 0,
                "decision_applied": 0,
                "continue_applied": 0,
                "system_message_applied": 0,
                "terminal_sequence_present": terminal_present,
                "emission_simulated": 0,
                "matcher_applied": 0,
                "include_processed": 0,
                "replaced_default_git": 1,
                "ansi_ignored": 0,
            }
        specific = body.get("hookSpecificOutput")
        if isinstance(specific, dict):
            path_raw = str(specific.get("worktreePath") or "")
        else:
            path_raw = ""
    else:
        raise SystemExit(f"unexpected hook type {hook_type}")

    if exit_code != 0 and hook_type == "command":
        return {
            "fires": 1,
            "supported": 1,
            "read_as": read_as,
            "creation_ok": 0,
            "creation_failed": 1,
            "fail": "nonzero",
            "path_not_used": 1,
            "session_exit_stated": 0,
            "decision_applied": 0,
            "continue_applied": 0,
            "system_message_applied": 0,
            "matcher_applied": 0,
            "include_processed": 0,
            "replaced_default_git": 1,
            "json_ignored": 1,
        }

    resolved, fail, rejected = classify_path(path_raw, layout.run_dir, layout.repo)
    base = {
        "fires": 1,
        "supported": 1,
        "read_as": read_as,
        "decision_applied": decision_applied,
        "continue_applied": continue_applied,
        "system_message_applied": system_message_applied,
        "terminal_sequence_present": terminal_present,
        "emission_simulated": 0,
        "matcher_applied": 0,
        "matcher_supported": 0,
        "include_processed": 0,
        "replaced_default_git": 1,
        "ansi_ignored": 1 if "\x1b[" in stdout else 0,
        "rejected": rejected,
    }
    if fail == "no_path":
        base.update(
            creation_ok=0,
            creation_failed=1,
            fail="no_path",
            session_exit_stated=0,
            adopted=0,
        )
        return base
    if fail == "rejected_component":
        base.update(
            creation_ok=0,
            creation_failed=1,
            fail="rejected_component",
            session_exit_stated=0,
            adopted=0,
        )
        return base
    if fail == "not_enterable":
        base.update(
            creation_ok=0,
            creation_failed=1,
            fail="not_enterable",
            session_exit=1,
            session_exit_stated=1,
            adopted=0,
        )
        return base

    gate = adopt(
        resolved,
        contained_in_git_repo=contained_in_git_repo,
        git_metadata=git_metadata,
    )
    env_src = os.path.join(layout.repo, ".env")
    env_dst = os.path.join(resolved, ".env")
    if copy_env and os.path.isfile(env_src):
        shutil.copyfile(env_src, env_dst)
    env_present = 1 if os.path.isfile(env_dst) else 0
    base.update(
        creation_ok=1 if gate["adopted"] else 0,
        creation_failed=0 if gate["adopted"] else 1,
        fail="none" if gate["adopted"] else str(gate["reason"]),
        session_exit_stated=0,
        adopted=gate["adopted"],
        refused=gate["refused"],
        dir_left=gate["dir_left"],
        path=resolved,
        env_present=env_present,
        copied_by_script=1 if copy_env and env_present else 0,
        contained_in_git_repo=1 if contained_in_git_repo else 0,
    )
    return base


def git_sees_changes(path: str, *, git_checkout: bool) -> int:
    """页上：用 git 找改动或未跟踪文件。不是 git checkout、也不在一个里面，就找不到。

    不跑 git。git_checkout 为假时，目录里有文件也看成干净。
    """
    if not git_checkout:
        return 0
    for _dirpath, _dirnames, filenames in os.walk(path):
        if filenames:
            return 1
    return 0


def settle_remove(
    *,
    hook_configured: bool,
    created_by_hook: bool,
    trigger: str,
    exit_code: int,
    directory_exists_after: bool,
    deleted_by_hook: bool,
    json_present: bool,
    matcher: str,
    git_recognized: bool,
    stored_path_symlink: bool,
    files_remain: bool,
    via: str,
    hook_checked_files: bool,
) -> dict[str, object]:
    """Remove 只清理 WorktreeCreate 钩子建出来的工作树。JSON 丢弃。"""
    json_discarded = 1 if json_present else 0
    if trigger in ("subagent_finish", "workflow_agent_finish"):
        return {
            "fires": 0,
            "kept": 1,
            "counts_as_removed": 0,
            "json_discarded": 0,
            "decision_applied": 0,
            "git_fallback": 0,
            "runtime_deletes_branch": 0,
        }
    if not created_by_hook:
        return {
            "fires": 0,
            "kept": 1,
            "counts_as_removed": 0,
            "default_git_cleanup_applies": 1 if trigger == "default_git_exit" else 0,
            "json_discarded": 0,
            "decision_applied": 0,
            "runtime_deletes_branch": 0,
        }
    if stored_path_symlink and trigger == "delete_background_session":
        return {
            "fires": 0,
            "hook_ran": 0,
            "refused_symlink": 1,
            "kept": 1,
            "counts_as_removed": 0,
            "decision_applied": 0,
            "json_discarded": json_discarded,
            "runtime_deletes_branch": 0,
        }
    if (
        trigger == "delete_background_session"
        and files_remain
        and via == "claude_rm"
    ):
        # 目录里还有文件时，claude rm 留下会话和工作树。
        # 没配 WorktreeRemove 时，agent view 那张表写：自己删目录，再跑一次 claude rm。
        kept = {
            "fires": 0,
            "hook_ran": 0,
            "session_kept": 1,
            "worktree_kept": 1,
            "counts_as_removed": 0,
            "decision_applied": 0,
            "json_discarded": 0,
            "runtime_deletes_branch": 0,
            "git_fallback": 0,
        }
        if not hook_configured:
            kept["dir_stayed"] = 1
            kept["instruction"] = "remove_directory_yourself"
        return kept
    if not hook_configured:
        if trigger in ("exit_session", "exit_worktree"):
            if git_recognized:
                return {
                    "fires": 0,
                    "hook_ran": 0,
                    "counts_as_removed": 1,
                    "fallback": "git_worktree_remove_force",
                    "stayed": 0,
                    "git_fallback": 1,
                    "decision_applied": 0,
                    "runtime_deletes_branch": 0,
                }
            return {
                "fires": 0,
                "hook_ran": 0,
                "counts_as_removed": 0,
                "stayed": 1,
                "fallback": "none_unrecognized",
                "git_fallback": 0,
                "decision_applied": 0,
                "runtime_deletes_branch": 0,
            }
        if trigger == "remote_control_cleanup":
            return {
                "fires": 0,
                "hook_ran": 0,
                "counts_as_removed": 0,
                "stayed": 1,
                "message": KEPT_PREFIX,
                "git_fallback": 0,
                "decision_applied": 0,
                "runtime_deletes_branch": 0,
            }
        if trigger == "delete_background_session":
            return {
                "fires": 0,
                "hook_ran": 0,
                "counts_as_removed": 0,
                "dir_stayed": 1,
                "instruction": "remove_directory_yourself",
                "git_fallback": 0,
                "decision_applied": 0,
                "runtime_deletes_branch": 0,
            }
    # 有钩子。后台会话删除、目录里还有文件：只有 agent view 确认时才跑。
    if trigger == "delete_background_session" and files_remain and via != "agent_view":
        return {
            "fires": 0,
            "hook_ran": 0,
            "kept": 1,
            "counts_as_removed": 0,
            "decision_applied": 0,
            "runtime_deletes_branch": 0,
        }
    fires = 1
    if deleted_by_hook:
        directory_exists_after = False
    if exit_code == 0:
        return {
            "fires": fires,
            "hook_ran": 1,
            "counts_as_removed": 1,
            "dir_exists": 0 if deleted_by_hook else 1,
            "trap": 0 if deleted_by_hook else 1,
            "json_discarded": json_discarded,
            "decision_applied": 0,
            "continue_applied": 0,
            "system_message_applied": 0,
            "matcher_applied": 0,
            "matcher_supported": 0,
            "git_fallback": 0,
            "runtime_deletes_branch": 0,
            "hook_checked_files": 1 if hook_checked_files else 0,
        }
    if directory_exists_after:
        failed = {
            "fires": fires,
            "hook_ran": 1,
            "counts_as_removed": 0,
            "stayed": 1,
            "dir_exists": 1,
            "git_fallback": 0,
            "json_discarded": json_discarded,
            "decision_applied": 0,
            "continue_applied": 0,
            "system_message_applied": 0,
            "matcher_applied": 0,
            "session_stays_on_background_delete": 1
            if trigger == "delete_background_session"
            else 0,
            "runtime_deletes_branch": 0,
            "hook_checked_files": 1 if hook_checked_files else 0,
        }
        if trigger == "remote_control_cleanup":
            failed["message"] = KEPT_PREFIX
        return failed
    return {
        "fires": fires,
        "hook_ran": 1,
        "counts_as_removed": 1,
        "dir_exists": 0,
        "git_fallback": 0,
        "json_discarded": json_discarded,
        "decision_applied": 0,
        "continue_applied": 0,
        "system_message_applied": 0,
        "matcher_applied": 0,
        "runtime_deletes_branch": 0,
        "hook_checked_files": 1 if hook_checked_files else 0,
    }


def build(layout: Layout) -> dict[str, Record]:
    rows: dict[str, Record] = {}
    good = layout.worktree("good")
    banner = (
        "\x1b[31mclaude hook banner\x1b[0m\n\n" + good + "\n"
    )
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=banner,
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_command_path_last_line"] = rec(
        "create_command_path_last_line",
        **flags,
        path_is_good=1 if flags.get("path") == good else 0,
    )

    ansi_line = f"\x1b[32m{good}\x1b[0m\n"
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="enter_worktree",
        hook_where="settings",
        flags=(),
        matcher="",
        exit_code=0,
        stdout=ansi_line,
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_ansi_on_path_line"] = rec(
        "create_ansi_on_path_line",
        **{k: v for k, v in flags.items() if k != "path"},
        path_is_good=1 if flags.get("path") == good else 0,
    )

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout="\n\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_command_no_path"] = rec("create_command_no_path", **flags)

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=1,
        stdout=good + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_command_exit1"] = rec("create_command_exit1", **flags)

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=2,
        stdout=good + "\n" + '{"decision":"block","continue":false}\n',
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    # 非零时路径不用。上面 stdout 最后一行不是路径，但 path_not_used 已盖住。
    rows["create_command_exit2_json"] = rec(
        "create_command_exit2_json",
        **flags,
        only_exit2=0,
    )

    flags = settle_create(
        layout,
        hook_type="http",
        configured=True,
        trigger="isolation_worktree",
        hook_where="settings",
        flags=(),
        matcher="",
        exit_code=0,
        stdout="",
        http_status=200,
        http_body={"hookSpecificOutput": {"hookEventName": "WorktreeCreate"}},
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_http_missing_path"] = rec("create_http_missing_path", **flags)

    flags = settle_create(
        layout,
        hook_type="http",
        configured=True,
        trigger="isolation_worktree",
        hook_where="settings",
        flags=(),
        matcher="",
        exit_code=0,
        stdout="",
        http_status=500,
        http_body={
            "hookSpecificOutput": {
                "hookEventName": "WorktreeCreate",
                "worktreePath": good,
            }
        },
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_http_non_2xx"] = rec("create_http_non_2xx", **flags)

    flags = settle_create(
        layout,
        hook_type="http",
        configured=True,
        trigger="background_session",
        hook_where="settings",
        flags=(),
        matcher="feature-auth",
        exit_code=0,
        stdout="",
        http_status=200,
        http_body={
            "continue": False,
            "systemMessage": "created",
            "terminalSequence": "\x07",
            "hookSpecificOutput": {
                "hookEventName": "WorktreeCreate",
                "worktreePath": good,
            },
        },
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_http_discards_fields"] = rec(
        "create_http_discards_fields",
        **{k: v for k, v in flags.items() if k != "path"},
        path_is_good=1 if flags.get("path") == good else 0,
    )

    json_only = '{"decision":"block","continue":false,"systemMessage":"no"}\n'
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=json_only,
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_command_json_read_as_path"] = rec(
        "create_command_json_read_as_path", **flags
    )

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=json_only + good + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_command_json_then_path"] = rec(
        "create_command_json_then_path",
        **{k: v for k, v in flags.items() if k != "path"},
        path_is_good=1 if flags.get("path") == good else 0,
    )

    rel_name = "rel-out"
    rel_dir = os.path.join(layout.root, rel_name)
    os.makedirs(rel_dir)
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=f"../{rel_name}\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_relative_collapses"] = rec(
        "create_relative_collapses",
        **{k: v for k, v in flags.items() if k != "path"},
        path_is_good=1 if flags.get("path") == rel_dir else 0,
    )

    dotted = os.path.join(layout.repo, "..", "made", "good")
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=dotted + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_absolute_dotdot_refused"] = rec(
        "create_absolute_dotdot_refused", **flags
    )

    dot_seg = good + "/./extra"
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=dot_seg + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_absolute_dot_refused"] = rec("create_absolute_dot_refused", **flags)

    outside = layout.worktree("via-link")
    link = os.path.join(layout.repo, "alias")
    if not os.path.lexists(link):
        os.symlink(outside, link)
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=link + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_symlink_below_root_refused"] = rec(
        "create_symlink_below_root_refused", **flags
    )

    file_path = os.path.join(layout.root, "not-a-dir")
    with open(file_path, "w", encoding="utf-8") as handle:
        handle.write("file\n")
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=file_path + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_path_not_directory"] = rec("create_path_not_directory", **flags)

    later = good + "\n\x1b[31mhook ready\x1b[0m\n"
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=later,
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_banner_after_path"] = rec("create_banner_after_path", **flags)

    include_wt = layout.worktree("include")
    with open(os.path.join(layout.repo, ".worktreeinclude"), "w", encoding="utf-8") as handle:
        handle.write(".env\n")
    with open(os.path.join(layout.repo, ".env"), "w", encoding="utf-8") as handle:
        handle.write("EXAMPLE=present\n")
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=include_wt + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_include_not_processed"] = rec(
        "create_include_not_processed",
        **{k: v for k, v in flags.items() if k != "path"},
    )

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=include_wt + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=True,
        version_before_2_1_300=False,
    )
    rows["create_script_copies_env"] = rec(
        "create_script_copies_env",
        **{k: v for k, v in flags.items() if k != "path"},
    )

    inside = os.path.join(layout.repo, "inside-wt")
    os.makedirs(inside, exist_ok=True)
    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=inside + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=True,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_inside_repo_refused"] = rec(
        "create_inside_repo_refused",
        **{k: v for k, v in flags.items() if k != "path"},
        dir_still_there=1 if os.path.isdir(inside) else 0,
    )

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="bash_git_worktree_add",
        hook_where="settings",
        flags=(),
        matcher="",
        exit_code=0,
        stdout=good + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_bash_does_not_fire"] = rec(
        "create_bash_does_not_fire",
        **flags,
        gate="PreToolUse",
        matcher="Bash",
    )

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="plugin",
        flags=("--worktree", "--tmux"),
        matcher="",
        exit_code=0,
        stdout=good + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_plugin_tmux_skips"] = rec("create_plugin_tmux_skips", **flags)

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree", "--tmux"),
        matcher="",
        exit_code=0,
        stdout=good + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_settings_tmux_runs"] = rec(
        "create_settings_tmux_runs",
        **{k: v for k, v in flags.items() if k != "path"},
        path_is_good=1 if flags.get("path") == good else 0,
    )

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="plugin",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=good + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_plugin_worktree_alone_runs"] = rec(
        "create_plugin_worktree_alone_runs",
        **{k: v for k, v in flags.items() if k != "path"},
        before_v2_1_300=0,
    )

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="claude_worktree",
        hook_where="plugin",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout=good + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=True,
    )
    rows["create_plugin_before_v2_1_300"] = rec(
        "create_plugin_before_v2_1_300",
        **flags,
        current=0,
    )

    flags = settle_create(
        layout,
        hook_type="command",
        configured=True,
        trigger="remote_control_worktree",
        hook_where="settings",
        flags=(),
        matcher="feature-auth",
        exit_code=0,
        stdout=good + "\n",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_matcher_ignored"] = rec(
        "create_matcher_ignored",
        **{k: v for k, v in flags.items() if k != "path"},
    )

    for kind in ("prompt", "agent"):
        flags = settle_create(
            layout,
            hook_type=kind,
            configured=True,
            trigger="claude_worktree",
            hook_where="settings",
            flags=("--worktree",),
            matcher="",
            exit_code=0,
            stdout=good + "\n",
            http_status=200,
            http_body=None,
            contained_in_git_repo=False,
            git_metadata=False,
            copy_env=False,
            version_before_2_1_300=False,
        )
        rows[f"create_{kind}_unsupported"] = rec(
            f"create_{kind}_unsupported",
            simulated=0,
            note="skip_or_error_not_stated",
            **flags,
        )

    flags = settle_create(
        layout,
        hook_type="mcp_tool",
        configured=True,
        trigger="claude_worktree",
        hook_where="settings",
        flags=("--worktree",),
        matcher="",
        exit_code=0,
        stdout="",
        http_status=200,
        http_body=None,
        contained_in_git_repo=False,
        git_metadata=False,
        copy_env=False,
        version_before_2_1_300=False,
    )
    rows["create_mcp_tool_path_unread"] = rec(
        "create_mcp_tool_path_unread",
        simulated=0,
        note="path_return_not_stated",
        **flags,
    )

    rows["create_wrong_event_name"] = rec(
        "create_wrong_event_name",
        simulated=0,
        note="wrong_event_name_not_stated",
        outcome_stated=0,
    )
    rows["create_multi_hook_winner"] = rec(
        "create_multi_hook_winner",
        simulated=0,
        note="winner_not_stated",
        outcome_stated=0,
    )

    # Remove 路径。钩子建出来的目录在 made/ 下。
    hook_wt = layout.worktree("hook-made")
    default_wt = layout.worktree("git-made")
    with open(os.path.join(hook_wt, "notes.txt"), "w", encoding="utf-8") as handle:
        handle.write("uncommitted\n")

    rows["remove_skips_default_git"] = rec(
        "remove_skips_default_git",
        **settle_remove(
            hook_configured=True,
            created_by_hook=False,
            trigger="default_git_exit",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=True,
            stored_path_symlink=False,
            files_remain=False,
            via="",
            hook_checked_files=False,
        ),
    )
    rows["subagent_finish_keeps"] = rec(
        "subagent_finish_keeps",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="subagent_finish",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="",
            hook_checked_files=False,
        ),
        create_on_isolation=1,
        exitworktree_available=0,
    )
    rows["workflow_finish_keeps"] = rec(
        "workflow_finish_keeps",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="workflow_agent_finish",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="",
            hook_checked_files=False,
        ),
    )

    gone = layout.worktree("exit0-gone")
    shutil.rmtree(gone)
    rows["remove_exit0_deleted"] = rec(
        "remove_exit0_deleted",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="exit_session",
            exit_code=0,
            directory_exists_after=False,
            deleted_by_hook=True,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=False,
            via="",
            hook_checked_files=True,
        ),
        dir_still_there=0 if not os.path.isdir(gone) else 1,
    )

    stayed = layout.worktree("exit0-stayed")
    rows["remove_exit0_dir_remains"] = rec(
        "remove_exit0_dir_remains",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="exit_session",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="",
            hook_checked_files=False,
        ),
        dir_still_there=1 if os.path.isdir(stayed) else 0,
    )

    rows["remove_nonzero_dir_remains"] = rec(
        "remove_nonzero_dir_remains",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="exit_worktree",
            exit_code=3,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=True,
            stored_path_symlink=False,
            files_remain=True,
            via="",
            hook_checked_files=True,
        ),
        only_exit2=0,
    )

    removed_late = layout.worktree("nonzero-gone")
    shutil.rmtree(removed_late)
    rows["remove_nonzero_dir_deleted"] = rec(
        "remove_nonzero_dir_deleted",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="exit_session",
            exit_code=1,
            directory_exists_after=False,
            deleted_by_hook=True,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=False,
            via="",
            hook_checked_files=False,
        ),
        dir_still_there=0 if not os.path.isdir(removed_late) else 1,
    )

    rows["remove_json_discarded_exit0"] = rec(
        "remove_json_discarded_exit0",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="exit_session",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=True,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="",
            hook_checked_files=False,
        ),
    )
    rows["remove_json_discarded_nonzero"] = rec(
        "remove_json_discarded_nonzero",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="remote_control_cleanup",
            exit_code=1,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=True,
            matcher="feature-auth",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="",
            hook_checked_files=False,
        ),
    )

    git_like = layout.worktree("fallback-git")
    fallback = settle_remove(
        hook_configured=False,
        created_by_hook=True,
        trigger="exit_session",
        exit_code=0,
        directory_exists_after=True,
        deleted_by_hook=False,
        json_present=False,
        matcher="",
        git_recognized=True,
        stored_path_symlink=False,
        files_remain=False,
        via="",
        hook_checked_files=False,
    )
    if fallback["counts_as_removed"] == 1:
        shutil.rmtree(git_like)
    rows["no_hook_exit_git_recognized"] = rec(
        "no_hook_exit_git_recognized",
        **fallback,
        dir_still_there=0 if not os.path.isdir(git_like) else 1,
    )

    unknown = layout.worktree("fallback-unknown")
    rows["no_hook_exit_unrecognized"] = rec(
        "no_hook_exit_unrecognized",
        **settle_remove(
            hook_configured=False,
            created_by_hook=True,
            trigger="exit_worktree",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="",
            hook_checked_files=False,
        ),
        dir_still_there=1 if os.path.isdir(unknown) else 1,
    )

    rows["no_hook_remote_control"] = rec(
        "no_hook_remote_control",
        **settle_remove(
            hook_configured=False,
            created_by_hook=True,
            trigger="remote_control_cleanup",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=True,
            stored_path_symlink=False,
            files_remain=False,
            via="",
            hook_checked_files=False,
        ),
    )
    rows["no_hook_background_delete"] = rec(
        "no_hook_background_delete",
        **settle_remove(
            hook_configured=False,
            created_by_hook=True,
            trigger="delete_background_session",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="claude_rm",
            hook_checked_files=False,
        ),
    )
    rows["bg_delete_agent_view_runs_hook"] = rec(
        "bg_delete_agent_view_runs_hook",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="delete_background_session",
            exit_code=0,
            directory_exists_after=False,
            deleted_by_hook=True,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="agent_view",
            hook_checked_files=True,
        ),
    )
    rows["bg_delete_claude_rm_keeps"] = rec(
        "bg_delete_claude_rm_keeps",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="delete_background_session",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="claude_rm",
            hook_checked_files=False,
        ),
    )
    rows["bg_delete_symlink_refused"] = rec(
        "bg_delete_symlink_refused",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="delete_background_session",
            exit_code=0,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=True,
            files_remain=False,
            via="agent_view",
            hook_checked_files=False,
        ),
    )
    rows["bg_delete_hook_fails_session_stays"] = rec(
        "bg_delete_hook_fails_session_stays",
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="delete_background_session",
            exit_code=1,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="agent_view",
            hook_checked_files=True,
        ),
        agent_view_reports_exit=1,
    )

    sees = git_sees_changes(hook_wt, git_checkout=False)
    rows["nongit_looks_clean"] = rec(
        "nongit_looks_clean",
        git_sees_changes=sees,
        files_present=1 if os.path.isfile(os.path.join(hook_wt, "notes.txt")) else 0,
        **settle_remove(
            hook_configured=True,
            created_by_hook=True,
            trigger="exit_session",
            exit_code=1,
            directory_exists_after=True,
            deleted_by_hook=False,
            json_present=False,
            matcher="",
            git_recognized=False,
            stored_path_symlink=False,
            files_remain=True,
            via="",
            hook_checked_files=True,
        ),
    )

    rows["remove_does_not_delete_branch"] = rec(
        "remove_does_not_delete_branch",
        runtime_deletes_branch=0,
        hook_may_delete_branch=1,
        counts_as_removed=1,
        branch_recorded="feature-auth",
    )
    rows["remove_matcher_ignored"] = rec(
        "remove_matcher_ignored",
        fires=1,
        matcher_supported=0,
        matcher_applied=0,
        matcher="feature-auth",
    )

    rows["sweep_keeps_hook_worktree"] = rec(
        "sweep_keeps_hook_worktree",
        has_git_marker=0,
        sweep_keeps=1,
        default_cleanup_applies=0,
    )
    rows["default_symlink_rule"] = rec(
        "default_symlink_rule",
        hook_configured=0,
        rule="default_git_symlink",
        names=".claude|.claude/worktrees|worktree_dir",
        hook_path_rule=0,
        refused=1,
    )
    rows["project_dir_stays"] = rec(
        "project_dir_stays",
        project_dir=layout.launch_root,
        cwd_after_enter=good,
        project_dir_follows=0,
        cwd_follows=1,
    )
    rows["matcher_row_disagrees"] = rec(
        "matcher_row_disagrees",
        reference_combined_has_cwd=0
        if "CwdChanged" not in REFERENCE_NO_MATCHER
        else 1,
        guide_combined_has_cwd=1 if "CwdChanged" in GUIDE_NO_MATCHER else 0,
        both_no_matcher=1,
        worktreecreate_in_both=1,
        worktreeremove_in_both=1,
    )
    rows["changelog_330"] = rec(
        "changelog_330",
        version="2.1.330",
        decision_rewrite_read=0,
        other_session_fix=1,
        fix_is_hook_decision=0,
    )
    rows["exitworktree_pages_not_merged"] = rec(
        "exitworktree_pages_not_merged",
        hook_page_expects_discard_changes=1,
        sdk_requires_discard_changes_for_dirty_git=1,
        sdk_remove_deletes_branch=1,
        hook_runtime_deletes_branch=0,
        merged=0,
    )
    rows["type_membership"] = rec(
        "type_membership",
        command=1,
        http=1,
        mcp_tool=1,
        prompt=0,
        agent=0,
        setup_in_this_pair=0,
    )
    rows["example_fields"] = rec(
        "example_fields",
        create_keys_ok=1,
        remove_keys_ok=1,
        create_has_name=1,
        remove_has_worktree_path=1,
    )
    rows["batch_side_note"] = rec(
        "batch_side_note",
        min_version="2.1.281",
        tutorial=0,
        needs_worktree_create_hook=1,
    )

    # 例子字段必须和专项 JSON 对齐。多出来的键算漂移。
    created = create_example(layout.repo)
    removed = remove_example(layout.repo, hook_wt)
    if set(created) != CREATE_EXAMPLE_KEYS or created["name"] != EXAMPLE_NAME:
        raise SystemExit("create example drifted")
    if set(removed) != REMOVE_EXAMPLE_KEYS or removed["worktree_path"] != hook_wt:
        raise SystemExit("remove example drifted")
    if "permission_mode" in created or "agent_id" in created:
        raise SystemExit("create example grew a field")
    rows["example_fields"].flags["create_name"] = created["name"]
    rows["example_fields"].flags["remove_event"] = removed["hook_event_name"]

    # 占位，避免未使用告警式阅读。default_wt 是「不是钩子建的」那条路径。
    if not os.path.isdir(default_wt):
        raise SystemExit("default git fixture dir missing")
    return rows


def check(rows: dict[str, Record]) -> None:
    expect(
        rows["create_command_path_last_line"],
        fires=1,
        creation_ok=1,
        creation_failed=0,
        read_as="path_line",
        path_is_good=1,
        ansi_ignored=1,
        decision_applied=0,
        include_processed=0,
        replaced_default_git=1,
        adopted=1,
    )
    expect(
        rows["create_ansi_on_path_line"],
        creation_ok=1,
        path_is_good=1,
        ansi_ignored=1,
        read_as="path_line",
    )
    expect(
        rows["create_command_no_path"],
        creation_failed=1,
        creation_ok=0,
        fail="no_path",
        session_exit_stated=0,
        decision_applied=0,
    )
    expect(
        rows["create_command_exit1"],
        creation_failed=1,
        fail="nonzero",
        path_not_used=1,
        decision_applied=0,
        session_exit_stated=0,
    )
    expect(
        rows["create_command_exit2_json"],
        creation_failed=1,
        fail="nonzero",
        path_not_used=1,
        json_ignored=1,
        decision_applied=0,
        only_exit2=0,
    )
    expect(
        rows["create_http_missing_path"],
        creation_failed=1,
        fail="no_path",
        read_as="hookSpecificOutput.worktreePath",
    )
    expect(
        rows["create_http_non_2xx"],
        creation_failed=1,
        fail="hook_failed",
        decision_applied=0,
    )
    expect(
        rows["create_http_discards_fields"],
        creation_ok=1,
        path_is_good=1,
        continue_applied=0,
        system_message_applied=0,
        terminal_sequence_present=1,
        emission_simulated=0,
        decision_applied=0,
        matcher_applied=0,
    )
    expect(
        rows["create_command_json_read_as_path"],
        read_as="path_line",
        decision_applied=0,
        continue_applied=0,
        system_message_applied=0,
        creation_failed=1,
        fail="not_enterable",
        session_exit=1,
        session_exit_stated=1,
    )
    expect(
        rows["create_command_json_then_path"],
        creation_ok=1,
        path_is_good=1,
        decision_applied=0,
        read_as="path_line",
    )
    expect(rows["create_relative_collapses"], creation_ok=1, path_is_good=1, fail="none")
    expect(
        rows["create_absolute_dotdot_refused"],
        creation_failed=1,
        fail="rejected_component",
        rejected="..",
        session_exit_stated=0,
    )
    expect(
        rows["create_absolute_dot_refused"],
        creation_failed=1,
        fail="rejected_component",
        rejected=".",
        session_exit_stated=0,
    )
    expect(
        rows["create_symlink_below_root_refused"],
        creation_failed=1,
        fail="rejected_component",
        rejected="alias",
        session_exit_stated=0,
    )
    expect(
        rows["create_path_not_directory"],
        creation_failed=1,
        fail="not_enterable",
        session_exit=1,
        session_exit_stated=1,
    )
    expect(
        rows["create_banner_after_path"],
        creation_failed=1,
        fail="not_enterable",
        session_exit=1,
        read_as="path_line",
    )
    expect(
        rows["create_include_not_processed"],
        include_processed=0,
        env_present=0,
        copied_by_script=0,
        replaced_default_git=1,
        creation_ok=1,
    )
    expect(
        rows["create_script_copies_env"],
        include_processed=0,
        env_present=1,
        copied_by_script=1,
        creation_ok=1,
    )
    expect(
        rows["create_inside_repo_refused"],
        adopted=0,
        refused=1,
        fail="git_resolves_working_tree",
        dir_left=1,
        dir_still_there=1,
        contained_in_git_repo=1,
    )
    expect(
        rows["create_bash_does_not_fire"],
        fires=0,
        creation_ok=0,
        pretooluse_gate=1,
        pretooluse_outcome_simulated=0,
        gate="PreToolUse",
        matcher="Bash",
    )
    expect(rows["create_plugin_tmux_skips"], fires=0, creation_ok=0)
    expect(rows["create_settings_tmux_runs"], fires=1, creation_ok=1, path_is_good=1)
    expect(
        rows["create_plugin_worktree_alone_runs"],
        fires=1,
        creation_ok=1,
        before_v2_1_300=0,
    )
    expect(
        rows["create_plugin_before_v2_1_300"],
        fires=0,
        current=0,
        creation_ok=0,
    )
    expect(
        rows["create_matcher_ignored"],
        fires=1,
        matcher_applied=0,
        matcher_supported=0,
        creation_ok=1,
    )
    expect(
        rows["create_prompt_unsupported"],
        simulated=0,
        note="skip_or_error_not_stated",
        supported=0,
        fires=0,
        outcome_stated=0,
        creation_ok=0,
    )
    expect(
        rows["create_agent_unsupported"],
        simulated=0,
        note="skip_or_error_not_stated",
        supported=0,
        outcome_stated=0,
    )
    expect(
        rows["create_mcp_tool_path_unread"],
        simulated=0,
        note="path_return_not_stated",
        supported=1,
        in_supported_set=1,
        path_return_stated=0,
        outcome_stated=0,
    )
    expect(
        rows["create_wrong_event_name"],
        simulated=0,
        note="wrong_event_name_not_stated",
        outcome_stated=0,
    )
    expect(
        rows["create_multi_hook_winner"],
        simulated=0,
        note="winner_not_stated",
        outcome_stated=0,
    )
    expect(
        rows["remove_skips_default_git"],
        fires=0,
        default_git_cleanup_applies=1,
        counts_as_removed=0,
    )
    expect(
        rows["subagent_finish_keeps"],
        fires=0,
        kept=1,
        counts_as_removed=0,
        create_on_isolation=1,
        exitworktree_available=0,
    )
    expect(rows["workflow_finish_keeps"], fires=0, kept=1, counts_as_removed=0)
    expect(
        rows["remove_exit0_deleted"],
        fires=1,
        counts_as_removed=1,
        dir_exists=0,
        trap=0,
        dir_still_there=0,
        runtime_deletes_branch=0,
        json_discarded=0,
    )
    expect(
        rows["remove_exit0_dir_remains"],
        counts_as_removed=1,
        dir_exists=1,
        trap=1,
        dir_still_there=1,
        decision_applied=0,
    )
    expect(
        rows["remove_nonzero_dir_remains"],
        counts_as_removed=0,
        stayed=1,
        dir_exists=1,
        git_fallback=0,
        only_exit2=0,
        decision_applied=0,
    )
    expect(
        rows["remove_nonzero_dir_deleted"],
        counts_as_removed=1,
        dir_exists=0,
        dir_still_there=0,
        git_fallback=0,
    )
    expect(
        rows["remove_json_discarded_exit0"],
        json_discarded=1,
        decision_applied=0,
        continue_applied=0,
        system_message_applied=0,
        counts_as_removed=1,
        dir_exists=1,
        trap=1,
    )
    expect(
        rows["remove_json_discarded_nonzero"],
        json_discarded=1,
        decision_applied=0,
        continue_applied=0,
        counts_as_removed=0,
        stayed=1,
        git_fallback=0,
        matcher_applied=0,
        message=KEPT_PREFIX,
    )
    expect(
        rows["no_hook_exit_git_recognized"],
        fires=0,
        counts_as_removed=1,
        fallback="git_worktree_remove_force",
        dir_still_there=0,
        runtime_deletes_branch=0,
    )
    expect(
        rows["no_hook_exit_unrecognized"],
        fires=0,
        counts_as_removed=0,
        stayed=1,
        fallback="none_unrecognized",
        dir_still_there=1,
    )
    expect(
        rows["no_hook_remote_control"],
        fires=0,
        stayed=1,
        counts_as_removed=0,
        message=KEPT_PREFIX,
        git_fallback=0,
    )
    expect(
        rows["no_hook_background_delete"],
        fires=0,
        hook_ran=0,
        dir_stayed=1,
        instruction="remove_directory_yourself",
        counts_as_removed=0,
    )
    expect(
        rows["bg_delete_agent_view_runs_hook"],
        fires=1,
        hook_ran=1,
        counts_as_removed=1,
        dir_exists=0,
    )
    expect(
        rows["bg_delete_claude_rm_keeps"],
        fires=0,
        hook_ran=0,
        session_kept=1,
        worktree_kept=1,
        counts_as_removed=0,
    )
    expect(
        rows["bg_delete_symlink_refused"],
        fires=0,
        hook_ran=0,
        refused_symlink=1,
        kept=1,
    )
    expect(
        rows["bg_delete_hook_fails_session_stays"],
        counts_as_removed=0,
        stayed=1,
        session_stays_on_background_delete=1,
        git_fallback=0,
        agent_view_reports_exit=1,
    )
    expect(
        rows["nongit_looks_clean"],
        git_sees_changes=0,
        files_present=1,
        hook_checked_files=1,
        counts_as_removed=0,
        stayed=1,
        git_fallback=0,
    )
    expect(
        rows["remove_does_not_delete_branch"],
        runtime_deletes_branch=0,
        hook_may_delete_branch=1,
        branch_recorded="feature-auth",
    )
    expect(
        rows["remove_matcher_ignored"],
        fires=1,
        matcher_supported=0,
        matcher_applied=0,
    )
    expect(
        rows["sweep_keeps_hook_worktree"],
        has_git_marker=0,
        sweep_keeps=1,
        default_cleanup_applies=0,
    )
    expect(
        rows["default_symlink_rule"],
        hook_configured=0,
        rule="default_git_symlink",
        hook_path_rule=0,
        refused=1,
    )
    expect(
        rows["project_dir_stays"],
        project_dir_follows=0,
        cwd_follows=1,
    )
    expect(
        rows["matcher_row_disagrees"],
        reference_combined_has_cwd=0,
        guide_combined_has_cwd=1,
        both_no_matcher=1,
        worktreecreate_in_both=1,
        worktreeremove_in_both=1,
    )
    expect(
        rows["changelog_330"],
        version="2.1.330",
        decision_rewrite_read=0,
        other_session_fix=1,
        fix_is_hook_decision=0,
    )
    expect(
        rows["exitworktree_pages_not_merged"],
        hook_page_expects_discard_changes=1,
        sdk_requires_discard_changes_for_dirty_git=1,
        sdk_remove_deletes_branch=1,
        hook_runtime_deletes_branch=0,
        merged=0,
    )
    expect(
        rows["type_membership"],
        command=1,
        http=1,
        mcp_tool=1,
        prompt=0,
        agent=0,
        setup_in_this_pair=0,
    )
    expect(
        rows["example_fields"],
        create_has_name=1,
        remove_has_worktree_path=1,
        create_name=EXAMPLE_NAME,
        remove_event="WorktreeRemove",
    )
    expect(
        rows["batch_side_note"],
        min_version="2.1.281",
        tutorial=0,
        needs_worktree_create_hook=1,
    )


def main() -> None:
    layout = make_layout()
    try:
        rows = build(layout)
        check(rows)
    finally:
        layout.close()
    for name in rows:
        print(rows[name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
