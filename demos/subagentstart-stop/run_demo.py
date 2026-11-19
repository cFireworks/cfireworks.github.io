#!/usr/bin/env python3
"""本地夹具：SubagentStart 不能拦开工，SubagentStop 才能留住收工。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不启动子代理，
不启动 agent team。这不是 settings 里的 hook。输入输出按 Hooks reference
的 SubagentStart / SubagentStop 专项、matcher 规则、退出码表、Decision
control、Exit code 2 与 continue: false，以及 prompt / agent 的类型名单和
Response schema，在本地走一遍。

另一只 SubagentStop hook 已经 block 或 exit 2，这一只再写 continue: false，
页上没有 TeammateIdle 那种「即使另一只已经 block」的句子。夹具标成
not_simulated，不算裁决。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 专项例子里的字符串。夹具引用，不访问这些路径。
START_CONTEXT = "Follow security guidelines for this task"
STOP_STDERR = "Tests are still failing."
STOP_REASON = "Run the test suite before finishing"
STOP_FEEDBACK = "Please run the test suite before finishing"
FILE_MISSING_STDERR = "No such file or directory"
HAND_BACK_CLOSING = "Analysis complete. Found 3 potential issues..."
PLUGIN_TYPE = "my-plugin:reviewer"
PLUGIN_EXTRA = "my-plugin:reviewer-extra"

# 冒号以外，精确名单只允许这些字符。多出来的字符走上正则路径。
EXACT_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ,|")

START_TYPES = frozenset({"command", "http", "mcp_tool"})
STOP_TYPES = frozenset({"command", "http", "mcp_tool", "prompt", "agent"})

# exit 2、stdout 为空、stderr 说文件缺失时，页上点名的是这几只。
FILE_MISSING_NAMED = frozenset(
    {"Stop", "SubagentStop", "TaskCompleted", "plugin:UserPromptSubmit"}
)
# onFailure 没有作用的那一组。exit 2 会把人送回去，钩子自己跑不起来时修不了。
ON_FAILURE_NO_EFFECT = frozenset(
    {"Stop", "SubagentStop", "TaskCompleted", "TeammateIdle"}
)
NO_MATCHER = frozenset(
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


def start_example() -> dict:
    """SubagentStart 专项例子。不补例子里没有的 permission_mode。"""
    return {
        "session_id": "abc123",
        "transcript_path": "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl",
        "cwd": "/Users/...",
        "hook_event_name": "SubagentStart",
        "agent_id": "agent-abc123",
        "agent_type": "Explore",
    }


def stop_example() -> dict:
    """SubagentStop 专项例子。两份数组留空，作用域按页上写的父会话。"""
    return {
        "session_id": "abc123",
        "transcript_path": "~/.claude/projects/.../abc123.jsonl",
        "cwd": "/Users/...",
        "permission_mode": "default",
        "hook_event_name": "SubagentStop",
        "stop_hook_active": False,
        "agent_id": "def456",
        "agent_type": "Explore",
        "agent_transcript_path": "~/.claude/projects/.../abc123/subagents/agent-def456.jsonl",
        "last_assistant_message": HAND_BACK_CLOSING,
        "background_tasks": [],
        "session_crons": [],
    }


def matcher_hits(matcher: str | None, agent_type: str) -> bool:
    """省略、空字符串、* 匹配全部。纯名字走精确匹配。带冒号等字符走未锚点正则。"""
    if matcher is None or matcher == "" or matcher == "*":
        return True
    if all(char in EXACT_CHARS for char in matcher):
        parts = [part.strip() for part in re.split(r"[|,]", matcher)]
        return agent_type in parts
    return re.search(matcher, agent_type) is not None


@dataclass
class Context:
    held: set[str] = field(default_factory=set)
    compacted: bool = False


@dataclass(frozen=True)
class StartVerdict:
    spawned: int
    blocks_spawn: int
    decision_control: int
    claude_sees_stderr: int
    notice_in_subagent_transcript: int
    notice_in_parent: int
    injected: int
    injection: str


def settle_start(exit_code: int, additional: str, ctx: Context) -> StartVerdict:
    """开工没有 decision control。exit 2 只在子代理自己的 transcript 里记一条通知。"""
    injected = 0
    injection = ""
    if additional:
        if ctx.compacted:
            ctx.held.discard(additional)
            ctx.compacted = False
        if additional not in ctx.held:
            ctx.held.add(additional)
            injected = 1
            injection = additional
    notice = 1 if exit_code == 2 else 0
    return StartVerdict(
        spawned=1,
        blocks_spawn=0,
        decision_control=0,
        claude_sees_stderr=0,
        notice_in_subagent_transcript=notice,
        notice_in_parent=0,
        injected=injected,
        injection=injection,
    )


@dataclass(frozen=True)
class HookOut:
    kind: str
    stderr: str = ""
    reason: str = ""
    additional: str = ""
    impossible: bool = False
    stdout_empty: bool = False


@dataclass(frozen=True)
class StopVerdict:
    simulated: int
    stopped: int
    continues: int
    feedback: str
    error_notice: int
    precedence: int
    non_blocking_file_missing: int
    note: str


def _file_missing(hook: HookOut) -> bool:
    return (
        hook.kind == "exit2"
        and hook.stdout_empty
        and "No such file or directory" in hook.stderr
    )


def settle_stop(hooks: tuple[HookOut, ...]) -> StopVerdict:
    """收工闸。同一份输出里 continue: false 优先于 exit 2，子代理结束这一轮。"""
    if any(hook.kind == "other_hook_unspecified" for hook in hooks):
        return StopVerdict(0, 0, 0, "", 0, 0, 0, "other_hook_not_stated")

    same = [hook for hook in hooks if hook.kind == "continue_false_and_exit2"]
    if same:
        return StopVerdict(1, 1, 0, "", 0, 1, 0, "continue_false_precedence")

    if any(_file_missing(hook) for hook in hooks):
        return StopVerdict(1, 1, 0, "", 0, 0, 1, "file_missing_non_blocking")

    for hook in hooks:
        if hook.kind == "exit2":
            return StopVerdict(1, 0, 1, hook.stderr, 0, 0, 0, "keeps_working")
        if hook.kind == "block":
            return StopVerdict(1, 0, 1, hook.reason, 0, 0, 0, "keeps_working")
        if hook.kind == "additional":
            return StopVerdict(1, 0, 1, hook.additional, 0, 0, 0, "non_error_feedback")
        if hook.kind == "prompt_block":
            if hook.impossible:
                return StopVerdict(1, 1, 0, "", 0, 0, 0, "impossible_allows_stop")
            return StopVerdict(1, 0, 1, hook.reason, 0, 0, 0, "prompt_keeps")
        if hook.kind == "agent_block":
            # agent 没有 continueOnBlock。ok: false 按该事件上 continueOnBlock: true 的 prompt 处理。
            # SubagentStop 的 prompt 在 ok: false 时本来就续工，除非 impossible。agent 不读 impossible。
            return StopVerdict(1, 0, 1, hook.reason, 0, 0, 0, "agent_keeps")
    return StopVerdict(1, 1, 0, "", 0, 0, 0, "allows_stop")


def parent_channel() -> dict:
    """交给父会话的通道写在 SubagentStop 专项末尾：PostToolUse，工具是 Agent。"""
    return {
        "event": "PostToolUse",
        "tool": "Agent",
        "subagentstop_targets_parent": 0,
    }


def handback_route() -> dict:
    """v2.1.271 起，报告不在 last_assistant_message。工具名以参考页和 tools-reference 为准。"""
    return {
        "docs_version": "2.1.271",
        "last_assistant_message_is_report": 0,
        "report_field": "tool_input.message",
        "matcher_tool": "SubagentHandback",
        "changelog_names_tool": 0,
    }


def array_scope(payload: dict) -> dict:
    """例子里的两份数组在，决策不把它们当成子代理自己的任务列表。"""
    return {
        "arrays_present": 1
        if "background_tasks" in payload and "session_crons" in payload
        else 0,
        "scope": "parent",
        "used_as_subagent_task_list": 0,
    }


def frontmatter_stop() -> dict:
    """子代理文件里写的 Stop，运行时接到 SubagentStop，结束就撤。"""
    return {"registered_as": "SubagentStop", "removed_when_finished": 1}


def agent_type_of(filename: str, frontmatter_name: str) -> str:
    """自定义子代理的 agent_type 是 frontmatter 的 name，不是文件名。"""
    del filename
    return frontmatter_name


@dataclass(frozen=True)
class Record:
    name: str
    simulated: int
    note: str
    flags: dict[str, object]

    def line(self) -> str:
        parts = [self.name, f"simulated={self.simulated}", f"note={self.note}"]
        for key, value in self.flags.items():
            parts.append(f"{key}={value}")
        return " ".join(parts)


def cases() -> list[Record]:
    fresh = Context()
    first = settle_start(0, START_CONTEXT, fresh)
    second = settle_start(0, START_CONTEXT, fresh)
    compacted = Context(held={START_CONTEXT}, compacted=True)
    after = settle_start(0, START_CONTEXT, compacted)
    blocked = settle_start(2, "", Context())
    rows = [
        Record(
            "start_exit2_notice",
            1,
            "spawn_proceeds",
            {
                "spawned": blocked.spawned,
                "blocks_spawn": blocked.blocks_spawn,
                "decision_control": blocked.decision_control,
                "claude_sees_stderr": blocked.claude_sees_stderr,
                "notice_in_subagent_transcript": blocked.notice_in_subagent_transcript,
                "notice_in_parent": blocked.notice_in_parent,
            },
        ),
        Record(
            "start_context_injected",
            1,
            "before_first_prompt",
            {"injected": first.injected, "injection": first.injection},
        ),
        Record(
            "start_context_held",
            1,
            "cache_kept",
            {"injected": second.injected, "held": 1},
        ),
        Record(
            "start_context_after_compact",
            1,
            "reinjected",
            {"injected": after.injected},
        ),
        Record(
            "start_no_decision_control",
            1,
            "context_only",
            {"decision_control": 0, "blocks_spawn": 0, "prompt_supported": 0, "agent_supported": 0},
        ),
    ]

    def stop_row(name: str, hooks: tuple[HookOut, ...], **extra: object) -> Record:
        verdict = settle_stop(hooks)
        flags: dict[str, object] = {
            "stopped": verdict.stopped,
            "continues": verdict.continues,
            "feedback": verdict.feedback,
            "error_notice": verdict.error_notice,
            "precedence": verdict.precedence,
            "non_blocking_file_missing": verdict.non_blocking_file_missing,
        }
        flags.update(extra)
        return Record(name, verdict.simulated, verdict.note, flags)

    rows.extend(
        [
            stop_row("stop_exit2_keeps", (HookOut("exit2", stderr=STOP_STDERR),)),
            stop_row("stop_block_keeps", (HookOut("block", reason=STOP_REASON),)),
            stop_row(
                "stop_additional_keeps",
                (HookOut("additional", additional=STOP_FEEDBACK),),
            ),
            stop_row("stop_exit0_allows", (HookOut("allow"),)),
            stop_row(
                "stop_continue_false_overrides_exit2",
                (HookOut("continue_false_and_exit2", stderr=STOP_STDERR),),
            ),
            stop_row(
                "stop_other_hook_continue_false",
                (
                    HookOut("exit2", stderr=STOP_STDERR),
                    HookOut("other_hook_unspecified"),
                ),
            ),
            stop_row(
                "stop_file_missing_nonblocking",
                (
                    HookOut(
                        "exit2",
                        stderr=FILE_MISSING_STDERR,
                        stdout_empty=True,
                    ),
                ),
                named=1 if "SubagentStop" in FILE_MISSING_NAMED else 0,
            ),
            stop_row(
                "prompt_ok_false_keeps",
                (HookOut("prompt_block", reason=STOP_REASON),),
                prompt_supported=1,
            ),
            stop_row(
                "prompt_impossible_allows_stop",
                (HookOut("prompt_block", reason=STOP_REASON, impossible=True),),
            ),
            stop_row(
                "agent_ok_false_keeps",
                (HookOut("agent_block", reason=STOP_REASON),),
                agent_supported=1,
            ),
        ]
    )

    channel = parent_channel()
    route = handback_route()
    scope = array_scope(stop_example())
    converted = frontmatter_stop()
    rows.extend(
        [
            Record(
                "matcher_exact_type",
                1,
                "agent_type",
                {
                    "explore_hit": int(matcher_hits("Explore", "Explore")),
                    "plan_hit": int(matcher_hits("Explore", "Plan")),
                },
            ),
            Record(
                "matcher_plugin_unanchored",
                1,
                "false_positive",
                {
                    "extra_hit": int(matcher_hits(PLUGIN_TYPE, PLUGIN_EXTRA)),
                    "bare_hit": int(matcher_hits(PLUGIN_TYPE, PLUGIN_TYPE)),
                },
            ),
            Record(
                "matcher_plugin_anchored",
                1,
                "exact",
                {
                    "extra_hit": int(matcher_hits(f"^{PLUGIN_TYPE}$", PLUGIN_EXTRA)),
                    "bare_hit": int(matcher_hits(f"^{PLUGIN_TYPE}$", PLUGIN_TYPE)),
                },
            ),
            Record(
                "matcher_empty_named",
                1,
                "internal_agent",
                {"hit": int(matcher_hits("Explore", ""))},
            ),
            Record(
                "matcher_empty_omitted",
                1,
                "matches_empty",
                {"hit": int(matcher_hits(None, ""))},
            ),
            Record(
                "matcher_empty_blank",
                1,
                "matches_empty",
                {"hit": int(matcher_hits("", ""))},
            ),
            Record(
                "matcher_empty_star",
                1,
                "matches_empty",
                {"hit": int(matcher_hits("*", ""))},
            ),
            Record(
                "matcher_empty_regex",
                1,
                "matches_empty",
                {"hit": int(matcher_hits(".*", ""))},
            ),
            Record(
                "name_not_filename",
                1,
                "frontmatter_name",
                {
                    "agent_type": agent_type_of("reviewer.md", "security-reviewer"),
                    "filename_hit": int(matcher_hits("reviewer.md", "security-reviewer")),
                    "name_hit": int(matcher_hits("security-reviewer", "security-reviewer")),
                },
            ),
            Record(
                "frontmatter_stop_becomes_subagentstop",
                1,
                "while_running",
                {
                    "registered_as": converted["registered_as"],
                    "removed_when_finished": converted["removed_when_finished"],
                },
            ),
            Record(
                "parent_via_posttooluse",
                1,
                "agent_tool",
                {
                    "event": channel["event"],
                    "tool": channel["tool"],
                    "subagentstop_targets_parent": channel["subagentstop_targets_parent"],
                },
            ),
            Record(
                "handback_report_elsewhere",
                1,
                "tool_input_message",
                {
                    "docs_version": route["docs_version"],
                    "last_assistant_message_is_report": route["last_assistant_message_is_report"],
                    "report_field": route["report_field"],
                    "matcher_tool": route["matcher_tool"],
                    "changelog_names_tool": route["changelog_names_tool"],
                },
            ),
            Record(
                "parent_scoped_arrays",
                1,
                "not_subagent_tasks",
                scope,
            ),
            Record(
                "teammateidle_no_matcher",
                1,
                "other_event",
                {
                    "matcher_supported": 0 if "TeammateIdle" in NO_MATCHER else 1,
                    "start_matcher_supported": 0 if "SubagentStart" in NO_MATCHER else 1,
                    "goes_idle": 1,
                    "same_event_as_subagent_stop": 0,
                    "on_failure_effect": 0 if "SubagentStop" in ON_FAILURE_NO_EFFECT else 1,
                },
            ),
        ]
    )
    return rows


def expect(record: Record, **flags: object) -> None:
    for key, value in flags.items():
        if key == "simulated":
            actual = record.simulated
        elif key == "note":
            actual = record.note
        else:
            actual = record.flags[key]
        if actual != value:
            raise SystemExit(f"{record.name} {key}: got {actual!r}, want {value!r}")


def check(records: dict[str, Record]) -> None:
    start = start_example()
    if set(start) != {
        "session_id",
        "transcript_path",
        "cwd",
        "hook_event_name",
        "agent_id",
        "agent_type",
    }:
        raise SystemExit("start example grew a field the page sample does not have")
    if "permission_mode" in start or start["agent_type"] != "Explore":
        raise SystemExit("start example drifted")

    stop = stop_example()
    if stop["agent_transcript_path"].split("/")[-2:] != ["subagents", "agent-def456.jsonl"]:
        raise SystemExit("agent transcript is not under subagents/")
    if stop["transcript_path"] == stop["agent_transcript_path"]:
        raise SystemExit("parent transcript and agent transcript collapsed")
    if stop["background_tasks"] or stop["session_crons"]:
        raise SystemExit("example arrays are not the empty parent-scoped samples")

    if START_TYPES & {"prompt", "agent"}:
        raise SystemExit("SubagentStart was given a prompt or agent type")
    if not {"prompt", "agent"} <= STOP_TYPES:
        raise SystemExit("SubagentStop lost prompt or agent")

    expect(
        records["start_exit2_notice"],
        spawned=1,
        blocks_spawn=0,
        decision_control=0,
        claude_sees_stderr=0,
        notice_in_subagent_transcript=1,
        notice_in_parent=0,
    )
    expect(records["start_context_injected"], injected=1, injection=START_CONTEXT)
    expect(records["start_context_held"], injected=0, held=1)
    expect(records["start_context_after_compact"], injected=1)
    expect(
        records["start_no_decision_control"],
        decision_control=0,
        blocks_spawn=0,
        prompt_supported=0,
        agent_supported=0,
    )
    expect(records["stop_exit2_keeps"], continues=1, stopped=0, feedback=STOP_STDERR)
    expect(records["stop_block_keeps"], continues=1, stopped=0, feedback=STOP_REASON)
    expect(
        records["stop_additional_keeps"],
        continues=1,
        stopped=0,
        feedback=STOP_FEEDBACK,
        error_notice=0,
        note="non_error_feedback",
    )
    expect(records["stop_exit0_allows"], stopped=1, continues=0, note="allows_stop")
    expect(
        records["stop_continue_false_overrides_exit2"],
        stopped=1,
        continues=0,
        precedence=1,
        note="continue_false_precedence",
    )
    expect(
        records["stop_other_hook_continue_false"],
        simulated=0,
        note="other_hook_not_stated",
        stopped=0,
        continues=0,
    )
    expect(
        records["stop_file_missing_nonblocking"],
        stopped=1,
        continues=0,
        non_blocking_file_missing=1,
        named=1,
    )
    expect(
        records["matcher_exact_type"],
        explore_hit=1,
        plan_hit=0,
    )
    expect(records["matcher_plugin_unanchored"], extra_hit=1, bare_hit=1)
    expect(records["matcher_plugin_anchored"], extra_hit=0, bare_hit=1)
    expect(records["matcher_empty_named"], hit=0)
    expect(records["matcher_empty_omitted"], hit=1)
    expect(records["matcher_empty_blank"], hit=1)
    expect(records["matcher_empty_star"], hit=1)
    expect(records["matcher_empty_regex"], hit=1)
    expect(
        records["name_not_filename"],
        agent_type="security-reviewer",
        filename_hit=0,
        name_hit=1,
    )
    expect(
        records["frontmatter_stop_becomes_subagentstop"],
        registered_as="SubagentStop",
        removed_when_finished=1,
    )
    expect(
        records["prompt_ok_false_keeps"],
        continues=1,
        stopped=0,
        feedback=STOP_REASON,
        prompt_supported=1,
    )
    expect(records["prompt_impossible_allows_stop"], stopped=1, continues=0)
    expect(records["agent_ok_false_keeps"], continues=1, stopped=0, feedback=STOP_REASON)
    expect(
        records["parent_via_posttooluse"],
        event="PostToolUse",
        tool="Agent",
        subagentstop_targets_parent=0,
    )
    expect(
        records["handback_report_elsewhere"],
        docs_version="2.1.271",
        last_assistant_message_is_report=0,
        report_field="tool_input.message",
        matcher_tool="SubagentHandback",
        changelog_names_tool=0,
    )
    expect(
        records["parent_scoped_arrays"],
        arrays_present=1,
        scope="parent",
        used_as_subagent_task_list=0,
    )
    expect(
        records["teammateidle_no_matcher"],
        matcher_supported=0,
        start_matcher_supported=1,
        goes_idle=1,
        same_event_as_subagent_stop=0,
        on_failure_effect=0,
    )
    if "prompt" in START_TYPES or "agent" in START_TYPES:
        raise SystemExit("start types drifted")


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
