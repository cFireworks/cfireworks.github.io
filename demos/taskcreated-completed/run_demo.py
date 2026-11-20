#!/usr/bin/env python3
"""本地夹具：TaskCreated 回滚创建，TaskCompleted 拦住勾完。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不启动真实 Task
工具，不启动 agent team。这不是 settings 里的 hook。输入输出按 Hooks
reference 的 TaskCreated / TaskCompleted 专项、退出码表、Decision control、
文件缺失那条 non-blocking 规则、onFailure 名单，以及 prompt / agent 的
Response schema，在本地走一遍。

同一份 TaskCompleted 输出里同时 exit 2 和 continue: false，页上写的是
「另一只 hook 已经 block」。同一份输出自己怎么裁决，没有写成 Stop 那句
「字段优先」。队友收工路径上这一格标成 not_simulated，不算结果。
TaskCreated 和 TaskUpdate 路径上，专项写了 continue: false 被忽略，
所以那两格照样算。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 专项 bash 例子里的 stderr。夹具引用，不执行那份脚本，也不跑 npm test。
TICKET_STDERR = (
    "Task subject must start with a ticket number, e.g. '[TICKET-123] Add feature'"
)
TICKET_OK = "[TICKET-123] Add feature"
EXAMPLE_SUBJECT = "Implement user authentication"
COMPLETED_STDERR = (
    "Tests not passing. Fix failing tests before completing: " + EXAMPLE_SUBJECT
)
# decision 的 reason 是夹具自己的句子，用来和 stderr 分开。页上的 JSON 是 "..."。
CREATED_REASON = "Subject does not match the project naming rule"
COMPLETED_REASON = "Completion criteria are not met"
STOP_REASON = "Task still in progress"
FILE_MISSING_STDERR = "No such file or directory"
PROMPT_REASON = "Completion criteria are not met"

EXAMPLE_SESSION = "abc123"
EXAMPLE_TRANSCRIPT = (
    "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl"
)
EXAMPLE_CWD = "/Users/..."
EXAMPLE_TASK_ID = "task-001"
EXAMPLE_DESCRIPTION = "Add login and signup endpoints"
EXAMPLE_TEAMMATE = "implementer"
EXAMPLE_TEAM = "session-a1b2c3d4"

# bash 例子：^\[TICKET-[0-9]+\] 。Python 的 match 同样从开头锚。
TICKET_RE = re.compile(r"^\[TICKET-[0-9]+\]")

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
# 指南把 CwdChanged 写进了同一行。分行不一致，语义两边都是 no matcher support。
GUIDE_NO_MATCHER = REFERENCE_NO_MATCHER | {"CwdChanged"}

FILE_MISSING_NAMED = frozenset(
    {"Stop", "SubagentStop", "TaskCompleted", "plugin:UserPromptSubmit"}
)
ON_FAILURE_NO_EFFECT = frozenset(
    {"Stop", "SubagentStop", "TaskCompleted", "TeammateIdle"}
)
FIVE_TYPES = frozenset({"command", "http", "mcp_tool", "prompt", "agent"})

# 退出码表里用来做方向对照的四格。不展开后三只旧文的套件。
EXIT2_EFFECT = {
    "Stop": "prevents_stop",
    "SubagentStart": "stderr_to_user_only",
    "TaskCreated": "rolls_back_creation",
    "TaskCompleted": "prevents_mark_completed",
}


def created_example() -> dict:
    """TaskCreated 专项例子。不补例子里没有的 permission_mode 和 agent_id。"""
    return {
        "session_id": EXAMPLE_SESSION,
        "transcript_path": EXAMPLE_TRANSCRIPT,
        "cwd": EXAMPLE_CWD,
        "hook_event_name": "TaskCreated",
        "task_id": EXAMPLE_TASK_ID,
        "task_subject": EXAMPLE_SUBJECT,
        "task_description": EXAMPLE_DESCRIPTION,
        "teammate_name": EXAMPLE_TEAMMATE,
        "team_name": EXAMPLE_TEAM,
    }


def completed_example() -> dict:
    """TaskCompleted 专项例子。比 Created 多一个 permission_mode。"""
    payload = created_example()
    payload["hook_event_name"] = "TaskCompleted"
    payload["permission_mode"] = "default"
    return payload


def ticket_script_exit(subject: str) -> int:
    """页上那份 bash：subject 对不上票据前缀就 exit 2。不跑 shell。"""
    if TICKET_RE.match(subject):
        return 0
    return 2


@dataclass(frozen=True)
class HookOut:
    """一只 hook 的输出。只覆盖页上写清的形状。"""

    exit_code: int = 0
    stderr: str = ""
    decision: str = ""
    reason: str = ""
    continue_false: bool = False
    stop_reason: str = ""
    stdout_empty: bool = True
    kind: str = "command"
    ok: bool = True
    continue_on_block: bool = False
    impossible: bool = False


def _file_missing(hook: HookOut) -> bool:
    return (
        hook.exit_code == 2
        and hook.stdout_empty
        and not hook.decision
        and FILE_MISSING_STDERR in hook.stderr
    )


def _command_block(hook: HookOut) -> tuple[str, str] | None:
    """命令钩是否拦住。文件缺失的例外由调用方按事件名单决定。

    同一只钩既 exit 2 又给出 decision block 时，消息用 reason。
    这是退出码 2 那一节的总述，不是 TaskCreated 自己另写的合并规则。
    continue: false 不是 blocking decision，不改这条消息来源。
    """
    if hook.kind != "command":
        return None
    if _file_missing(hook):
        return ("file_missing", hook.stderr)
    has_exit = hook.exit_code == 2
    has_block = hook.decision == "block"
    if has_exit and has_block:
        return ("reason", hook.reason)
    if has_block:
        return ("reason", hook.reason)
    if has_exit:
        return ("stderr", hook.stderr)
    return None


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


def settle_created(
    hook: HookOut,
    *,
    has_task_tools: bool,
    has_task_create: bool,
    tool: str,
) -> dict[str, object]:
    """TaskCreate 才开火。block 删任务并把消息当工具错误。continue: false 被忽略。"""
    if tool != "TaskCreate" or not has_task_tools or not has_task_create:
        return {
            "fires": 0,
            "deleted": 0,
            "task_kept": 0,
            "claude_keeps_working": 0,
            "blocks_turn": 0,
            "continue_false_ignored": 0,
            "message_from": "none",
            "non_blocking_exception": 0,
        }
    block = _command_block(hook)
    ignored = 1 if hook.continue_false else 0
    if block and block[0] == "file_missing":
        # 名单里没有 TaskCreated。例外不套用，exit 2 仍回滚。
        return {
            "fires": 1,
            "deleted": 1,
            "task_kept": 0,
            "claude_keeps_working": 1,
            "blocks_turn": 0,
            "continue_false_ignored": ignored,
            "message_from": "stderr",
            "tool_error": block[1],
            "non_blocking_exception": 0,
            "named_in_file_missing_rule": 0,
        }
    if block:
        return {
            "fires": 1,
            "deleted": 1,
            "task_kept": 0,
            "claude_keeps_working": 1,
            "blocks_turn": 0,
            "continue_false_ignored": ignored,
            "message_from": block[0],
            "tool_error": block[1],
            "non_blocking_exception": 0,
        }
    return {
        "fires": 1,
        "deleted": 0,
        "task_kept": 1,
        "claude_keeps_working": 1,
        "blocks_turn": 0,
        "continue_false_ignored": ignored,
        "message_from": "none",
        "non_blocking_exception": 0,
    }


def settle_completed(hooks: list[HookOut], *, path: str) -> dict[str, object]:
    """TaskUpdate 忽略 continue: false。队友收工时，这个字段放它闲下来。

    path 只取 task_update 或 teammate_turn。同一只钩同时 exit 2 和
    continue: false，在队友收工路径上不裁决。
    """
    if path not in {"task_update", "teammate_turn"}:
        raise SystemExit(f"unknown path {path}")
    if (
        path == "teammate_turn"
        and len(hooks) == 1
        and hooks[0].exit_code == 2
        and hooks[0].continue_false
        and hooks[0].kind == "command"
    ):
        return {
            "path": path,
            "simulated_outcome": 0,
            "marked_completed": 0,
            "teammate_idle": 0,
            "teammate_working": 0,
        }

    real_blocks: list[tuple[str, str]] = []
    continue_false = [hook for hook in hooks if hook.continue_false and hook.kind == "command"]
    file_missing_only = True
    saw_file_missing = False
    for hook in hooks:
        block = _command_block(hook)
        if block is None:
            if hook.kind == "command" and not hook.continue_false:
                file_missing_only = False
            continue
        if block[0] == "file_missing":
            saw_file_missing = True
            # TaskCompleted 在名单里。这一只钩的 exit 2 不算拦住。
            continue
        file_missing_only = False
        real_blocks.append(block)

    if path == "task_update":
        ignored = 1 if continue_false else 0
        if real_blocks:
            source, message = _prefer_reason(real_blocks)
            return {
                "path": path,
                "fires": 1,
                "marked_completed": 0,
                "stays_open": 1,
                "still_in_progress": 0,
                "turn_continues": 1,
                "blocks_turn": 0,
                "teammate_idle": 0,
                "continue_false_ignored": ignored,
                "feedback_from": source,
                "feedback": message,
                "non_blocking": 0,
            }
        marked = 1
        return {
            "path": path,
            "fires": 1,
            "marked_completed": marked,
            "stays_open": 0,
            "still_in_progress": 0,
            "turn_continues": 1,
            "blocks_turn": 0,
            "teammate_idle": 0,
            "continue_false_ignored": ignored,
            "feedback_from": "none",
            "non_blocking": 1 if saw_file_missing and file_missing_only else 0,
            "named_in_file_missing_rule": 1 if saw_file_missing else 0,
        }

    # 队友收工。continue: false 优先到「闲下来、任务仍进行中」，即使另一只已经 block。
    if continue_false:
        stop_reason = continue_false[0].stop_reason
        return {
            "path": path,
            "fires": 1,
            "marked_completed": 0,
            "stays_open": 0,
            "still_in_progress": 1,
            "teammate_idle": 1,
            "teammate_working": 0,
            "blocks_turn": 0,
            "overrode_other_block": 1 if real_blocks else 0,
            "stop_reason_in_transcript": 1 if stop_reason else 0,
            "stop_reason": stop_reason,
            "continue_false_ignored": 0,
        }
    if real_blocks:
        source, message = _prefer_reason(real_blocks)
        return {
            "path": path,
            "fires": 1,
            "marked_completed": 0,
            "stays_open": 1,
            "still_in_progress": 0,
            "teammate_idle": 0,
            "teammate_working": 1,
            "blocks_turn": 0,
            "overrode_other_block": 0,
            "feedback_from": source,
            "feedback": message,
            "continue_false_ignored": 0,
        }
    return {
        "path": path,
        "fires": 1,
        "marked_completed": 1,
        "stays_open": 0,
        "still_in_progress": 0,
        "teammate_idle": 0,
        "teammate_working": 0,
        "blocks_turn": 0,
        "overrode_other_block": 0,
        "continue_false_ignored": 0,
    }


def _prefer_reason(blocks: list[tuple[str, str]]) -> tuple[str, str]:
    for source, message in blocks:
        if source == "reason":
            return source, message
    return blocks[0]


def settle_prompt(
    event: str,
    path: str,
    hook: HookOut,
) -> dict[str, object]:
    """ok: false 的三条。impossible 在这两只事件上不采用。

    agent hook 按同一事件上 continueOnBlock true 的 prompt hook 处理。
    """
    if hook.ok:
        return {"turn_continues": 1, "allows": 1, "impossible_honored": 0}
    effective_cob = True if hook.kind == "agent" else hook.continue_on_block
    base = {
        "impossible_honored": 0,
        "impossible_seen": 1 if hook.impossible else 0,
        "hook_type": hook.kind,
        "blocks_turn": 0,
    }
    if event == "TaskCreated":
        base.update(
            {
                "message_as": "tool_error",
                "turn_continues": 1,
                "continue_on_block_matters": 0,
                "continue_on_block": int(hook.continue_on_block),
                "feedback": hook.reason,
            }
        )
        return base
    if event == "TaskCompleted" and path == "task_update":
        base.update(
            {
                "message_as": "tool_result",
                "turn_continues": 1,
                "continue_on_block_matters": 0,
                "continue_on_block": int(effective_cob if hook.kind == "agent" else hook.continue_on_block),
                "feedback": hook.reason,
            }
        )
        return base
    if event == "TaskCompleted" and path == "teammate_turn":
        if effective_cob:
            base.update(
                {
                    "goes_idle": 0,
                    "keeps_working": 1,
                    "reason_to_teammate": 1,
                    "reason_in_transcript": 0,
                    "continue_on_block": 1,
                    "feedback": hook.reason,
                }
            )
        else:
            base.update(
                {
                    "goes_idle": 1,
                    "keeps_working": 0,
                    "reason_to_teammate": 0,
                    "reason_in_transcript": 1,
                    "continue_on_block": 0,
                    "feedback": hook.reason,
                }
            )
        return base
    raise SystemExit(f"prompt path not stated for {event} {path}")


def matcher_applied(event: str, matcher: str | None) -> int:
    """不支持 matcher 的事件，配置了也不筛。"""
    if event in REFERENCE_NO_MATCHER:
        return 0
    return 0 if matcher is None else 1


def cases() -> list[Record]:
    rows: list[Record] = []

    def add(name: str, flags: dict[str, object], *, simulated: int = 1, note: str = "ok") -> None:
        rows.append(Record(name, simulated, note, flags))

    add(
        "created_exit2_rolls_back",
        settle_created(
            HookOut(exit_code=2, stderr=TICKET_STDERR),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        ),
    )
    add(
        "created_block_rolls_back",
        settle_created(
            HookOut(decision="block", reason=CREATED_REASON, stdout_empty=False),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        ),
    )
    add(
        "created_exit2_continue_false",
        settle_created(
            HookOut(
                exit_code=2,
                stderr=TICKET_STDERR,
                continue_false=True,
                stdout_empty=False,
            ),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        ),
    )
    add(
        "created_continue_false_alone",
        settle_created(
            HookOut(continue_false=True, stop_reason="stop", stdout_empty=False),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        ),
    )
    add(
        "created_exit0_keeps",
        settle_created(
            HookOut(exit_code=0),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        ),
    )
    reject = ticket_script_exit(EXAMPLE_SUBJECT)
    add(
        "created_ticket_subject_rejects",
        settle_created(
            HookOut(exit_code=reject, stderr=TICKET_STDERR if reject == 2 else ""),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        )
        | {"script_exit": reject, "subject": EXAMPLE_SUBJECT},
    )
    allow = ticket_script_exit(TICKET_OK)
    add(
        "created_ticket_subject_allows",
        settle_created(
            HookOut(exit_code=allow),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        )
        | {"script_exit": allow, "subject": TICKET_OK},
    )
    add(
        "created_no_task_tools",
        settle_created(
            HookOut(exit_code=0),
            has_task_tools=False,
            has_task_create=False,
            tool="TaskCreate",
        ),
        note="no_task_tools",
    )
    add(
        "created_todowrite_instead",
        settle_created(
            HookOut(exit_code=0),
            has_task_tools=True,
            has_task_create=False,
            tool="TodoWrite",
        )
        | {"has_task_create": 0},
        note="todo_write_instead",
    )
    add(
        "created_matcher_ignored",
        settle_created(
            HookOut(exit_code=0),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        )
        | {
            "matcher_supported": 0,
            "matcher_applied": matcher_applied("TaskCreated", "Explore"),
            "configured": "Explore",
            "agent_type": "Plan",
            "subject_filtered": matcher_applied("TaskCreated", EXAMPLE_SUBJECT),
        },
    )
    add(
        "created_bash_does_not_fire",
        settle_created(
            HookOut(exit_code=2, stderr=TICKET_STDERR),
            has_task_tools=True,
            has_task_create=True,
            tool="Bash",
        )
        | {"tool": "Bash"},
        note="not_every_tool_call",
    )
    add(
        "created_exit2_and_block_uses_reason",
        settle_created(
            HookOut(
                exit_code=2,
                stderr=TICKET_STDERR,
                decision="block",
                reason=CREATED_REASON,
                stdout_empty=False,
            ),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        ),
    )
    add(
        "created_file_missing_still_rolls_back",
        settle_created(
            HookOut(exit_code=2, stderr=FILE_MISSING_STDERR, stdout_empty=True),
            has_task_tools=True,
            has_task_create=True,
            tool="TaskCreate",
        ),
    )

    prompt_false = HookOut(kind="prompt", ok=False, reason=PROMPT_REASON, stdout_empty=False)
    prompt_false_cob = HookOut(
        kind="prompt",
        ok=False,
        reason=PROMPT_REASON,
        continue_on_block=True,
        stdout_empty=False,
    )
    prompt_impossible = HookOut(
        kind="prompt",
        ok=False,
        reason=PROMPT_REASON,
        impossible=True,
        stdout_empty=False,
    )
    agent_false = HookOut(kind="agent", ok=False, reason=PROMPT_REASON, stdout_empty=False)

    add("created_prompt_ok_false", settle_prompt("TaskCreated", "task_create", prompt_false))
    add(
        "created_prompt_ok_false_cob",
        settle_prompt("TaskCreated", "task_create", prompt_false_cob),
    )
    add(
        "created_prompt_impossible",
        settle_prompt("TaskCreated", "task_create", prompt_impossible),
    )
    add("created_agent_ok_false", settle_prompt("TaskCreated", "task_create", agent_false))

    add(
        "update_exit2_stays_open",
        settle_completed(
            [HookOut(exit_code=2, stderr=COMPLETED_STDERR)],
            path="task_update",
        ),
    )
    add(
        "update_block_stays_open",
        settle_completed(
            [HookOut(decision="block", reason=COMPLETED_REASON, stdout_empty=False)],
            path="task_update",
        ),
    )
    add(
        "update_continue_false_ignored",
        settle_completed(
            [HookOut(continue_false=True, stop_reason=STOP_REASON, stdout_empty=False)],
            path="task_update",
        ),
    )
    add(
        "update_exit2_continue_false",
        settle_completed(
            [
                HookOut(
                    exit_code=2,
                    stderr=COMPLETED_STDERR,
                    continue_false=True,
                    stop_reason=STOP_REASON,
                    stdout_empty=False,
                )
            ],
            path="task_update",
        ),
    )
    add(
        "update_exit0_completes",
        settle_completed([HookOut(exit_code=0)], path="task_update"),
    )
    add(
        "update_prompt_ok_false",
        settle_prompt("TaskCompleted", "task_update", prompt_false),
    )
    add(
        "update_prompt_ok_false_cob",
        settle_prompt("TaskCompleted", "task_update", prompt_false_cob),
    )
    add(
        "update_prompt_impossible",
        settle_prompt("TaskCompleted", "task_update", prompt_impossible),
    )
    add(
        "update_agent_ok_false",
        settle_prompt("TaskCompleted", "task_update", agent_false),
    )
    add(
        "update_file_missing_nonblocking",
        settle_completed(
            [HookOut(exit_code=2, stderr=FILE_MISSING_STDERR, stdout_empty=True)],
            path="task_update",
        ),
    )
    add(
        "completed_matcher_ignored",
        settle_completed([HookOut(exit_code=2, stderr=COMPLETED_STDERR)], path="task_update")
        | {
            "matcher_supported": 0,
            "matcher_applied": matcher_applied("TaskCompleted", "Explore"),
            "configured": "Explore",
            "agent_type": "Plan",
        },
    )

    add(
        "teammate_exit2_keeps_working",
        settle_completed(
            [HookOut(exit_code=2, stderr=COMPLETED_STDERR)],
            path="teammate_turn",
        ),
    )
    add(
        "teammate_block_keeps_working",
        settle_completed(
            [HookOut(decision="block", reason=COMPLETED_REASON, stdout_empty=False)],
            path="teammate_turn",
        ),
    )
    add(
        "teammate_continue_false_idles",
        settle_completed(
            [HookOut(continue_false=True, stop_reason=STOP_REASON, stdout_empty=False)],
            path="teammate_turn",
        ),
    )
    add(
        "teammate_continue_false_overrides_exit2",
        settle_completed(
            [
                HookOut(exit_code=2, stderr=COMPLETED_STDERR),
                HookOut(continue_false=True, stop_reason=STOP_REASON, stdout_empty=False),
            ],
            path="teammate_turn",
        )
        | {"other": "exit2"},
    )
    add(
        "teammate_continue_false_overrides_block",
        settle_completed(
            [
                HookOut(decision="block", reason=COMPLETED_REASON, stdout_empty=False),
                HookOut(continue_false=True, stop_reason=STOP_REASON, stdout_empty=False),
            ],
            path="teammate_turn",
        )
        | {"other": "block"},
    )
    same = settle_completed(
        [
            HookOut(
                exit_code=2,
                stderr=COMPLETED_STDERR,
                continue_false=True,
                stop_reason=STOP_REASON,
                stdout_empty=False,
            )
        ],
        path="teammate_turn",
    )
    add(
        "teammate_same_hook_exit2_continue_false",
        same,
        simulated=int(same["simulated_outcome"]),
        note="same_output_not_stated",
    )
    add(
        "teammate_exit0_allows",
        settle_completed([HookOut(exit_code=0)], path="teammate_turn"),
    )
    add(
        "teammate_prompt_default_idles",
        settle_prompt("TaskCompleted", "teammate_turn", prompt_false),
    )
    add(
        "teammate_prompt_continue_on_block",
        settle_prompt("TaskCompleted", "teammate_turn", prompt_false_cob),
    )
    add(
        "teammate_prompt_impossible_ignored",
        settle_prompt("TaskCompleted", "teammate_turn", prompt_impossible),
    )
    add(
        "teammate_agent_ok_false_keeps",
        settle_prompt("TaskCompleted", "teammate_turn", agent_false),
    )

    add(
        "contrast_stop",
        {
            "can_block": 1,
            "effect": EXIT2_EFFECT["Stop"],
            "blocks_turn": 1,
            "blocks_list": 0,
            "blocks_spawn": 0,
        },
        note="minimal",
    )
    add(
        "contrast_subagentstart",
        {
            "can_block": 0,
            "effect": EXIT2_EFFECT["SubagentStart"],
            "blocks_turn": 0,
            "blocks_list": 0,
            "blocks_spawn": 0,
        },
        note="minimal",
    )
    add(
        "contrast_created_list",
        {
            "can_block": 1,
            "effect": EXIT2_EFFECT["TaskCreated"],
            "blocks_turn": 0,
            "blocks_list": 1,
            "blocks_spawn": 0,
        },
        note="minimal",
    )
    add(
        "contrast_completed_list",
        {
            "can_block": 1,
            "effect": EXIT2_EFFECT["TaskCompleted"],
            "blocks_turn": 0,
            "blocks_list": 1,
            "blocks_spawn": 0,
        },
        note="minimal",
    )
    add(
        "taskstop_not_checklist",
        {
            "fires_taskcreated": 0,
            "fires_taskcompleted": 0,
            "marks_list_complete": 0,
            "stops_background": 1,
        },
        note="not_this_list",
    )
    add(
        "mcp_tasks_different_list",
        {"same_list": 0, "fires_taskcreated": 0, "fires_taskcompleted": 0},
        note="not_this_event",
    )
    add(
        "scheduled_not_hook_decision",
        {
            "same_list": 0,
            "decision_rewrite_read": 0,
            "tasks_ui_lists_scheduled": 1,
            "version": "2.1.329",
        },
        note="tasks_ui",
    )
    add(
        "on_failure_membership",
        {
            "taskcreated_named": int("TaskCreated" in ON_FAILURE_NO_EFFECT),
            "taskcompleted_named": int("TaskCompleted" in ON_FAILURE_NO_EFFECT),
            "teammateidle_named": int("TeammateIdle" in ON_FAILURE_NO_EFFECT),
        },
        note="membership_only",
    )
    add(
        "file_missing_membership",
        {
            "taskcreated_named": int("TaskCreated" in FILE_MISSING_NAMED),
            "taskcompleted_named": int("TaskCompleted" in FILE_MISSING_NAMED),
        },
        note="membership_only",
    )
    add(
        "cwd_row_disagrees",
        {
            "reference_combined_has_cwd": int("CwdChanged" in REFERENCE_NO_MATCHER),
            "guide_combined_has_cwd": int("CwdChanged" in GUIDE_NO_MATCHER),
            "both_no_matcher": 1,
            "taskcreated_in_both": int(
                "TaskCreated" in REFERENCE_NO_MATCHER and "TaskCreated" in GUIDE_NO_MATCHER
            ),
        },
        note="row_placement",
    )
    created = created_example()
    completed = completed_example()
    add(
        "example_fields",
        {
            "created_has_agent_id": int("agent_id" in created),
            "completed_has_agent_id": int("agent_id" in completed),
            "created_has_permission_mode": int("permission_mode" in created),
            "completed_has_permission_mode": int("permission_mode" in completed),
            "team_name_deprecated": 1,
            "agent_id_min": "2.1.290",
            "agent_id_may_be_absent": 1,
            "created_types": len(FIVE_TYPES),
            "completed_types": len(FIVE_TYPES),
        },
    )
    return rows


def expect(record: Record, **flags: object) -> None:
    if "simulated" in flags and record.simulated != flags.pop("simulated"):
        raise SystemExit(
            f"{record.name} simulated: got {record.simulated!r}, want check failed"
        )
    if "note" in flags and record.note != flags.pop("note"):
        raise SystemExit(f"{record.name} note: got {record.note!r}, want {flags}")
    for key, value in flags.items():
        actual = record.flags[key]
        if actual != value:
            raise SystemExit(f"{record.name} {key}: got {actual!r}, want {value!r}")


def check(records: dict[str, Record]) -> None:
    created = created_example()
    completed = completed_example()
    if set(created) != {
        "session_id",
        "transcript_path",
        "cwd",
        "hook_event_name",
        "task_id",
        "task_subject",
        "task_description",
        "teammate_name",
        "team_name",
    }:
        raise SystemExit("created example grew a field the page sample does not have")
    if "permission_mode" in created or "agent_id" in created:
        raise SystemExit("created example drifted")
    extra = set(completed) - set(created)
    if completed["permission_mode"] != "default" or extra != {"permission_mode"}:
        raise SystemExit("completed example drifted")
    if "agent_id" in created or "agent_id" in completed:
        raise SystemExit("example grew an agent_id the page sample does not have")
    if created["team_name"] != EXAMPLE_TEAM or created["teammate_name"] != EXAMPLE_TEAMMATE:
        raise SystemExit("example names drifted")
    if ticket_script_exit(EXAMPLE_SUBJECT) != 2 or ticket_script_exit(TICKET_OK) != 0:
        raise SystemExit("ticket prefix check drifted from the bash example")
    if FIVE_TYPES != {"command", "http", "mcp_tool", "prompt", "agent"}:
        raise SystemExit("hook types drifted")

    expect(
        records["created_exit2_rolls_back"],
        fires=1,
        deleted=1,
        task_kept=0,
        claude_keeps_working=1,
        blocks_turn=0,
        continue_false_ignored=0,
        message_from="stderr",
        tool_error=TICKET_STDERR,
    )
    expect(
        records["created_block_rolls_back"],
        fires=1,
        deleted=1,
        task_kept=0,
        claude_keeps_working=1,
        blocks_turn=0,
        message_from="reason",
        tool_error=CREATED_REASON,
    )
    expect(
        records["created_exit2_continue_false"],
        fires=1,
        deleted=1,
        task_kept=0,
        claude_keeps_working=1,
        blocks_turn=0,
        continue_false_ignored=1,
        message_from="stderr",
        tool_error=TICKET_STDERR,
    )
    expect(
        records["created_continue_false_alone"],
        fires=1,
        deleted=0,
        task_kept=1,
        claude_keeps_working=1,
        blocks_turn=0,
        continue_false_ignored=1,
        message_from="none",
    )
    expect(
        records["created_exit0_keeps"],
        fires=1,
        deleted=0,
        task_kept=1,
        claude_keeps_working=1,
        blocks_turn=0,
        message_from="none",
    )
    expect(
        records["created_ticket_subject_rejects"],
        script_exit=2,
        deleted=1,
        tool_error=TICKET_STDERR,
        claude_keeps_working=1,
    )
    expect(
        records["created_ticket_subject_allows"],
        script_exit=0,
        deleted=0,
        task_kept=1,
        subject=TICKET_OK,
    )
    expect(records["created_no_task_tools"], fires=0, deleted=0, note="no_task_tools")
    expect(
        records["created_todowrite_instead"],
        fires=0,
        has_task_create=0,
        note="todo_write_instead",
    )
    expect(
        records["created_matcher_ignored"],
        fires=1,
        matcher_supported=0,
        matcher_applied=0,
        subject_filtered=0,
        configured="Explore",
        agent_type="Plan",
    )
    expect(records["created_bash_does_not_fire"], fires=0, tool="Bash", note="not_every_tool_call")
    expect(
        records["created_exit2_and_block_uses_reason"],
        deleted=1,
        message_from="reason",
        tool_error=CREATED_REASON,
        claude_keeps_working=1,
    )
    expect(
        records["created_file_missing_still_rolls_back"],
        named_in_file_missing_rule=0,
        non_blocking_exception=0,
        deleted=1,
        message_from="stderr",
        claude_keeps_working=1,
    )
    expect(
        records["created_prompt_ok_false"],
        message_as="tool_error",
        turn_continues=1,
        continue_on_block_matters=0,
        continue_on_block=0,
        impossible_honored=0,
        blocks_turn=0,
        feedback=PROMPT_REASON,
    )
    expect(
        records["created_prompt_ok_false_cob"],
        message_as="tool_error",
        turn_continues=1,
        continue_on_block_matters=0,
        continue_on_block=1,
    )
    expect(
        records["created_prompt_impossible"],
        impossible_honored=0,
        impossible_seen=1,
        message_as="tool_error",
        turn_continues=1,
    )
    expect(
        records["created_agent_ok_false"],
        hook_type="agent",
        message_as="tool_error",
        turn_continues=1,
        continue_on_block_matters=0,
    )

    expect(
        records["update_exit2_stays_open"],
        path="task_update",
        marked_completed=0,
        stays_open=1,
        turn_continues=1,
        blocks_turn=0,
        teammate_idle=0,
        continue_false_ignored=0,
        feedback_from="stderr",
        feedback=COMPLETED_STDERR,
    )
    expect(
        records["update_block_stays_open"],
        marked_completed=0,
        stays_open=1,
        turn_continues=1,
        blocks_turn=0,
        feedback_from="reason",
        feedback=COMPLETED_REASON,
    )
    expect(
        records["update_continue_false_ignored"],
        marked_completed=1,
        stays_open=0,
        turn_continues=1,
        blocks_turn=0,
        teammate_idle=0,
        continue_false_ignored=1,
    )
    expect(
        records["update_exit2_continue_false"],
        marked_completed=0,
        stays_open=1,
        turn_continues=1,
        blocks_turn=0,
        continue_false_ignored=1,
        feedback_from="stderr",
        feedback=COMPLETED_STDERR,
    )
    expect(records["update_exit0_completes"], marked_completed=1, stays_open=0, turn_continues=1)
    expect(
        records["update_prompt_ok_false"],
        message_as="tool_result",
        turn_continues=1,
        continue_on_block_matters=0,
        continue_on_block=0,
        blocks_turn=0,
        impossible_honored=0,
    )
    expect(
        records["update_prompt_ok_false_cob"],
        message_as="tool_result",
        turn_continues=1,
        continue_on_block_matters=0,
        continue_on_block=1,
    )
    expect(
        records["update_prompt_impossible"],
        impossible_honored=0,
        message_as="tool_result",
        turn_continues=1,
    )
    expect(
        records["update_agent_ok_false"],
        hook_type="agent",
        message_as="tool_result",
        turn_continues=1,
        continue_on_block_matters=0,
    )
    expect(
        records["update_file_missing_nonblocking"],
        path="task_update",
        named_in_file_missing_rule=1,
        non_blocking=1,
        marked_completed=1,
        stays_open=0,
    )
    expect(
        records["completed_matcher_ignored"],
        fires=1,
        matcher_supported=0,
        matcher_applied=0,
        marked_completed=0,
        stays_open=1,
    )

    expect(
        records["teammate_exit2_keeps_working"],
        path="teammate_turn",
        marked_completed=0,
        stays_open=1,
        teammate_working=1,
        teammate_idle=0,
        blocks_turn=0,
        overrode_other_block=0,
        feedback_from="stderr",
    )
    expect(
        records["teammate_block_keeps_working"],
        stays_open=1,
        teammate_working=1,
        teammate_idle=0,
        feedback_from="reason",
        feedback=COMPLETED_REASON,
        blocks_turn=0,
    )
    expect(
        records["teammate_continue_false_idles"],
        marked_completed=0,
        still_in_progress=1,
        teammate_idle=1,
        teammate_working=0,
        blocks_turn=0,
        overrode_other_block=0,
        stop_reason_in_transcript=1,
        stop_reason=STOP_REASON,
        continue_false_ignored=0,
    )
    expect(
        records["teammate_continue_false_overrides_exit2"],
        marked_completed=0,
        still_in_progress=1,
        teammate_idle=1,
        teammate_working=0,
        overrode_other_block=1,
        other="exit2",
        blocks_turn=0,
        stop_reason=STOP_REASON,
    )
    expect(
        records["teammate_continue_false_overrides_block"],
        marked_completed=0,
        still_in_progress=1,
        teammate_idle=1,
        overrode_other_block=1,
        other="block",
        blocks_turn=0,
    )
    expect(
        records["teammate_same_hook_exit2_continue_false"],
        simulated=0,
        note="same_output_not_stated",
        simulated_outcome=0,
        marked_completed=0,
        teammate_idle=0,
        teammate_working=0,
    )
    expect(
        records["teammate_exit0_allows"],
        marked_completed=1,
        teammate_idle=0,
        teammate_working=0,
        blocks_turn=0,
    )
    expect(
        records["teammate_prompt_default_idles"],
        goes_idle=1,
        keeps_working=0,
        reason_in_transcript=1,
        reason_to_teammate=0,
        continue_on_block=0,
        impossible_honored=0,
        blocks_turn=0,
    )
    expect(
        records["teammate_prompt_continue_on_block"],
        goes_idle=0,
        keeps_working=1,
        reason_to_teammate=1,
        reason_in_transcript=0,
        continue_on_block=1,
    )
    expect(
        records["teammate_prompt_impossible_ignored"],
        impossible_honored=0,
        impossible_seen=1,
        goes_idle=1,
        keeps_working=0,
    )
    expect(
        records["teammate_agent_ok_false_keeps"],
        hook_type="agent",
        keeps_working=1,
        goes_idle=0,
        reason_to_teammate=1,
        continue_on_block=1,
    )

    expect(
        records["contrast_stop"],
        can_block=1,
        effect="prevents_stop",
        blocks_turn=1,
        blocks_list=0,
        blocks_spawn=0,
        note="minimal",
    )
    expect(
        records["contrast_subagentstart"],
        can_block=0,
        effect="stderr_to_user_only",
        blocks_spawn=0,
        blocks_list=0,
        blocks_turn=0,
    )
    expect(
        records["contrast_created_list"],
        can_block=1,
        effect="rolls_back_creation",
        blocks_list=1,
        blocks_turn=0,
    )
    expect(
        records["contrast_completed_list"],
        can_block=1,
        effect="prevents_mark_completed",
        blocks_list=1,
        blocks_turn=0,
    )
    expect(
        records["taskstop_not_checklist"],
        fires_taskcompleted=0,
        fires_taskcreated=0,
        marks_list_complete=0,
        stops_background=1,
    )
    expect(records["mcp_tasks_different_list"], same_list=0, fires_taskcreated=0)
    expect(
        records["scheduled_not_hook_decision"],
        same_list=0,
        decision_rewrite_read=0,
        tasks_ui_lists_scheduled=1,
        version="2.1.329",
    )
    expect(
        records["on_failure_membership"],
        taskcreated_named=0,
        taskcompleted_named=1,
        teammateidle_named=1,
    )
    expect(
        records["file_missing_membership"],
        taskcreated_named=0,
        taskcompleted_named=1,
    )
    expect(
        records["cwd_row_disagrees"],
        reference_combined_has_cwd=0,
        guide_combined_has_cwd=1,
        both_no_matcher=1,
        taskcreated_in_both=1,
    )
    expect(
        records["example_fields"],
        created_has_agent_id=0,
        completed_has_agent_id=0,
        created_has_permission_mode=0,
        completed_has_permission_mode=1,
        team_name_deprecated=1,
        agent_id_min="2.1.290",
        agent_id_may_be_absent=1,
        created_types=5,
        completed_types=5,
    )


def main() -> None:
    rows = cases()
    records = {row.name: row for row in rows}
    if len(records) != len(rows):
        raise SystemExit("duplicate case name")
    check(records)
    for row in rows:
        print(row.line())
    print("result=pass")


if __name__ == "__main__":
    main()
