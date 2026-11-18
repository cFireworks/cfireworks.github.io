#!/usr/bin/env python3
"""本地夹具：TeammateIdle 的 exit 2 拦住空闲，continue: false 放它闲下来。

不调用 API，不读密钥，不访问网络，不启动 Claude Code，不启动 agent team。
这不是 settings 里的 hook。输入输出按 Hooks reference 的 TeammateIdle 专项、
退出码表、Decision control、prompt / agent 的 Response schema，以及
Agent SDK 表上的 onFailure 句子在本地走一遍。

同一只 hook 里同时 exit 2 和 continue: false，页上没有把 TeammateIdle
写成 Stop 那句「字段优先」。夹具标成 not_simulated，不算结果。
「stderr 说文件缺失就当成 non-blocking error」那条没有点名 TeammateIdle。
MCP 等待句没有点名它。这两处也不算结果。
"""

from __future__ import annotations

from dataclasses import dataclass

EXAMPLE_SESSION_ID = "abc123"
EXAMPLE_TRANSCRIPT = (
    "/Users/.../.claude/projects/.../00893aaf-19fa-41d2-8238-13269b9b3ca0.jsonl"
)
EXAMPLE_CWD = "/Users/..."
EXAMPLE_TEAMMATE = "researcher"
EXAMPLE_TEAM = "session-a1b2c3d4"
# 参考页 bash 例子里的 stderr。夹具引用这句，不执行那份脚本。
ARTIFACT_STDERR = "Build artifact missing. Run the build before stopping."

# 退出码 2 且 stdout 为空、stderr 报文件缺失时，页上点名的是这几只。
FILE_MISSING_NAMED = frozenset(
    {"Stop", "SubagentStop", "TaskCompleted", "plugin:UserPromptSubmit"}
)
# MCP：能拦的例子是 PreToolUse、Stop；观察性例子是 Notification、SessionEnd。
MCP_WAIT_NAMED = frozenset({"PreToolUse", "Stop"})
MCP_NO_WAIT_NAMED = frozenset({"Notification", "SessionEnd"})
# SDK callback 失败时忽略 onFailure: "block" 的事件。
ON_FAILURE_IGNORED = frozenset(
    {"Stop", "SubagentStop", "TaskCompleted", "TeammateIdle"}
)
# 表上的 SDK 回调。只记 TeammateIdle 这一行，不把 SessionStart 的句子套过来。
PYTHON_CALLBACK = False
TYPESCRIPT_CALLBACK = True


def example_payload(teammate_name: str = EXAMPLE_TEAMMATE) -> dict:
    """专项例子的字段。不补例子里没有的 agent_id。"""
    return {
        "session_id": EXAMPLE_SESSION_ID,
        "transcript_path": EXAMPLE_TRANSCRIPT,
        "cwd": EXAMPLE_CWD,
        "permission_mode": "default",
        "hook_event_name": "TeammateIdle",
        "teammate_name": teammate_name,
        "team_name": EXAMPLE_TEAM,
    }


@dataclass(frozen=True)
class HookOut:
    """一只 hook 的输出。kind 只覆盖页上写清的形状。"""

    kind: str
    stderr: str = ""
    reason: str = ""
    stop_reason: str = ""
    continue_on_block: bool = False


@dataclass(frozen=True)
class Verdict:
    simulated: int
    goes_idle: int
    continues_working: int
    feedback: str
    stop_reason_in_transcript: int
    reason_in_transcript: int
    overrode_other_block: int
    note: str


def artifact_gate(artifact_exists: bool) -> HookOut:
    """参考页例子的分支：缺 ./dist/output.js 则 stderr + exit 2，否则 exit 0。"""
    if not artifact_exists:
        return HookOut(kind="exit2", stderr=ARTIFACT_STDERR)
    return HookOut(kind="allow")


def script_for_teammate(name: str, artifact_exists: bool) -> HookOut:
    """matcher 不能按名字过滤。脚本可以读 teammate_name 再分支。

    team_name 不参与。名字不是例子里的 researcher 时，夹具走 exit 0。
    """
    if name == EXAMPLE_TEAMMATE:
        return artifact_gate(artifact_exists)
    return HookOut(kind="allow")


def _keeps_working(hook: HookOut) -> bool:
    if hook.kind == "exit2":
        return True
    if hook.kind == "block":
        return True
    if hook.kind == "prompt_block":
        return hook.continue_on_block
    if hook.kind == "agent_block":
        # agent 没有 continueOnBlock。ok: false 按 prompt 的 continueOnBlock: true 处理。
        return True
    return False


def settle_teammate_idle(hooks: tuple[HookOut, ...]) -> Verdict:
    """多只 TeammateIdle。continue: false 让它闲下来，即使另一只已经 block。"""
    if any(hook.kind == "same_hook_mix" for hook in hooks):
        return Verdict(0, 0, 0, "", 0, 0, 0, "not_simulated")

    idle_hooks = [hook for hook in hooks if hook.kind == "continue_false"]
    keepers = [hook for hook in hooks if _keeps_working(hook)]
    if idle_hooks:
        reason = idle_hooks[0].stop_reason
        return Verdict(
            simulated=1,
            goes_idle=1,
            continues_working=0,
            feedback="",
            stop_reason_in_transcript=1 if reason else 0,
            reason_in_transcript=0,
            overrode_other_block=1 if keepers else 0,
            note="goes_idle",
        )
    if keepers:
        hook = keepers[0]
        if hook.kind == "exit2":
            feedback = hook.stderr
        else:
            feedback = hook.reason
        return Verdict(
            simulated=1,
            goes_idle=0,
            continues_working=1,
            feedback=feedback,
            stop_reason_in_transcript=0,
            reason_in_transcript=0,
            overrode_other_block=0,
            note="keeps_working",
        )
    prompt_idle = [
        hook
        for hook in hooks
        if hook.kind == "prompt_block" and not hook.continue_on_block and hook.reason
    ]
    return Verdict(
        1,
        1,
        0,
        "",
        0,
        1 if prompt_idle else 0,
        0,
        "goes_idle",
    )


def settle_stop(exit_code: int, continue_false: bool) -> Verdict:
    """Stop 上 continue: false 优先于 exit 2，这一轮结束。最小对照，不重写停轮套件。"""
    if continue_false:
        return Verdict(1, 0, 0, "", 0, 0, 0, "turn_ended")
    if exit_code == 2:
        return Verdict(1, 0, 1, "", 0, 0, 0, "turn_continued")
    return Verdict(1, 0, 0, "", 0, 0, 0, "turn_ended")


def settle_session_end(exit_code: int) -> dict:
    """SessionEnd 的 exit 2 只把 stderr 给用户看，终止照旧。"""
    return {
        "blocks_termination": 0,
        "stderr_to_user": 1 if exit_code == 2 else 0,
        "turn_continued": 0,
    }


def matcher_filters(event: str, matcher: str | None) -> bool:
    """无 matcher 支持的事件：写了 matcher 也静默忽略，不能靠它过滤。"""
    no_matcher = {
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
    if event in no_matcher:
        return False
    return matcher not in (None, "", "*")


def sdk_on_failure(event: str, on_failure: str) -> dict:
    """callback 失败。和 command hook 的 exit 2 不是同一条路。"""
    ignored = event in ON_FAILURE_IGNORED and on_failure == "block"
    return {
        "on_failure_honored": 0 if ignored else 1,
        "action_goes_ahead": 1 if ignored else 0,
        "same_as_command_exit2": 0,
    }


@dataclass
class Case:
    name: str
    event: str
    teammate_name: str
    matcher: str | None
    hooks: tuple[HookOut, ...]
    artifact_exists: bool | None = None
    use_script_branch: bool = False
    team_name_a: str = EXAMPLE_TEAM
    team_name_b: str = EXAMPLE_TEAM
    stop_exit: int = 0
    stop_continue_false: bool = False
    session_exit: int = 0
    on_failure: str = ""
    prompt_supported: int = 1
    agent_supported: int = 1


@dataclass
class Record:
    name: str
    event: str
    event_fired: int
    handler_ran: int
    matcher_honored: int
    goes_idle: int
    continues_working: int
    feedback: str
    stop_reason_in_transcript: int
    reason_in_transcript: int
    overrode_other_block: int
    team_name_used: int
    agent_id_present: int
    agent_id_required: int
    blocks_termination: int
    stderr_to_user: int
    on_failure_honored: str
    action_goes_ahead: str
    python_callback: int
    typescript_callback: int
    named_in_file_missing_rule: int
    waits_for_server: str
    simulated: int
    note: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"event={self.event}",
                f"event_fired={self.event_fired}",
                f"handler_ran={self.handler_ran}",
                f"matcher_honored={self.matcher_honored}",
                f"goes_idle={self.goes_idle}",
                f"continues_working={self.continues_working}",
                f"feedback={self.feedback or '-'}",
                f"stop_reason_in_transcript={self.stop_reason_in_transcript}",
                f"reason_in_transcript={self.reason_in_transcript}",
                f"overrode_other_block={self.overrode_other_block}",
                f"team_name_used={self.team_name_used}",
                f"agent_id_present={self.agent_id_present}",
                f"agent_id_required={self.agent_id_required}",
                f"blocks_termination={self.blocks_termination}",
                f"stderr_to_user={self.stderr_to_user}",
                f"on_failure_honored={self.on_failure_honored}",
                f"action_goes_ahead={self.action_goes_ahead}",
                f"python_callback={self.python_callback}",
                f"typescript_callback={self.typescript_callback}",
                f"named_in_file_missing_rule={self.named_in_file_missing_rule}",
                f"waits_for_server={self.waits_for_server}",
                f"simulated={self.simulated}",
                f"note={self.note}",
            ]
        )


def cases() -> list[Case]:
    missing = artifact_gate(False)
    present = artifact_gate(True)
    block = HookOut(kind="block", reason="lint failed")
    allow_idle = HookOut(
        kind="continue_false", stop_reason="quality gate waived"
    )
    return [
        Case("exit2_keeps_working", "TeammateIdle", EXAMPLE_TEAMMATE, None, (missing,)),
        Case("block_keeps_working", "TeammateIdle", EXAMPLE_TEAMMATE, None, (block,)),
        Case("exit0_goes_idle", "TeammateIdle", EXAMPLE_TEAMMATE, None, (present,)),
        Case(
            "continue_false_overrides_block",
            "TeammateIdle",
            EXAMPLE_TEAMMATE,
            None,
            (block, allow_idle),
        ),
        Case(
            "continue_false_overrides_exit2",
            "TeammateIdle",
            EXAMPLE_TEAMMATE,
            None,
            (missing, allow_idle),
        ),
        Case(
            "matcher_ignored",
            "TeammateIdle",
            "fixture-other",
            "researcher",
            (),
            artifact_exists=False,
            use_script_branch=True,
        ),
        Case(
            "script_branches_on_name",
            "TeammateIdle",
            EXAMPLE_TEAMMATE,
            "researcher",
            (),
            artifact_exists=False,
            use_script_branch=True,
        ),
        Case(
            "team_name_ignored",
            "TeammateIdle",
            EXAMPLE_TEAMMATE,
            None,
            (missing,),
            team_name_a=EXAMPLE_TEAM,
            team_name_b="session-other",
        ),
        Case("agent_id_absent", "TeammateIdle", EXAMPLE_TEAMMATE, None, (missing,)),
        Case(
            "prompt_default_idle",
            "TeammateIdle",
            EXAMPLE_TEAMMATE,
            None,
            (HookOut(kind="prompt_block", reason="lint red", continue_on_block=False),),
        ),
        Case(
            "prompt_continue_on_block",
            "TeammateIdle",
            EXAMPLE_TEAMMATE,
            None,
            (HookOut(kind="prompt_block", reason="lint red", continue_on_block=True),),
        ),
        Case(
            "agent_ok_false_keeps",
            "TeammateIdle",
            EXAMPLE_TEAMMATE,
            None,
            (HookOut(kind="agent_block", reason="lint red"),),
        ),
        Case(
            "same_hook_mix_unspecified",
            "TeammateIdle",
            EXAMPLE_TEAMMATE,
            None,
            (HookOut(kind="same_hook_mix"),),
        ),
        Case(
            "sessionend_exit2",
            "SessionEnd",
            "",
            None,
            (),
            session_exit=2,
            prompt_supported=0,
            agent_supported=0,
        ),
        Case(
            "stop_continue_false",
            "Stop",
            "",
            None,
            (),
            stop_exit=2,
            stop_continue_false=True,
        ),
        Case(
            "sdk_on_failure_ignored",
            "TeammateIdle",
            EXAMPLE_TEAMMATE,
            None,
            (),
            on_failure="block",
        ),
        Case("file_missing_not_named", "TeammateIdle", EXAMPLE_TEAMMATE, None, ()),
        Case("mcp_wait_unspecified", "TeammateIdle", EXAMPLE_TEAMMATE, None, ()),
    ]


def settle(case: Case) -> Record:
    payload = example_payload(case.teammate_name or EXAMPLE_TEAMMATE)
    agent_id_present = 1 if "agent_id" in payload else 0
    team_name_used = 0
    event_fired = 1
    handler_ran = 0
    matcher_honored = 1 if matcher_filters(case.event, case.matcher) else 0
    goes_idle = 0
    continues_working = 0
    feedback = ""
    stop_reason_in_transcript = 0
    reason_in_transcript = 0
    overrode_other_block = 0
    blocks_termination = 0
    stderr_to_user = 0
    on_failure_honored = "-"
    action_goes_ahead = "-"
    named = 1 if case.event in FILE_MISSING_NAMED else 0
    if case.event in MCP_WAIT_NAMED:
        waits = "1"
    elif case.event in MCP_NO_WAIT_NAMED:
        waits = "0"
    else:
        waits = "unspecified"
    simulated = 1
    note = "idle_contract"

    if case.name == "team_name_ignored":
        left = settle_teammate_idle(case.hooks)
        right = settle_teammate_idle(case.hooks)
        if left != right or case.team_name_a == case.team_name_b:
            raise SystemExit("team_name changed the verdict or the pair was not distinct")
        verdict = left
        handler_ran = 1
        goes_idle = verdict.goes_idle
        continues_working = verdict.continues_working
        feedback = verdict.feedback
        stop_reason_in_transcript = verdict.stop_reason_in_transcript
        reason_in_transcript = verdict.reason_in_transcript
        overrode_other_block = verdict.overrode_other_block
        note = "team_name_deprecated"
    elif case.name == "file_missing_not_named":
        simulated = 0
        note = "not_named"
        event_fired = 0
        handler_ran = 0
    elif case.name == "mcp_wait_unspecified":
        simulated = 0
        note = "not_named"
        event_fired = 0
        handler_ran = 0
    elif case.event == "SessionEnd":
        end = settle_session_end(case.session_exit)
        blocks_termination = end["blocks_termination"]
        stderr_to_user = end["stderr_to_user"]
        continues_working = end["turn_continued"]
        goes_idle = 0
        handler_ran = 1
        note = "stderr_to_user_only"
        named = 0
        waits = "0"
    elif case.event == "Stop" and case.stop_continue_false:
        verdict = settle_stop(case.stop_exit, True)
        continues_working = verdict.continues_working
        handler_ran = 1
        note = verdict.note
        waits = "1"
    elif case.on_failure:
        failed = sdk_on_failure(case.event, case.on_failure)
        on_failure_honored = str(failed["on_failure_honored"])
        action_goes_ahead = str(failed["action_goes_ahead"])
        goes_idle = 1 if failed["action_goes_ahead"] else 0
        continues_working = 0
        handler_ran = 0
        note = "callback_failure"
    elif case.use_script_branch:
        if case.artifact_exists is None:
            raise SystemExit("script branch needs an artifact flag")
        hook = script_for_teammate(case.teammate_name, case.artifact_exists)
        verdict = settle_teammate_idle((hook,))
        handler_ran = 1
        goes_idle = verdict.goes_idle
        continues_working = verdict.continues_working
        feedback = verdict.feedback
        note = "script_read_teammate_name"
    else:
        verdict = settle_teammate_idle(case.hooks)
        simulated = verdict.simulated
        if verdict.simulated:
            handler_ran = 1
            goes_idle = verdict.goes_idle
            continues_working = verdict.continues_working
            feedback = verdict.feedback
            stop_reason_in_transcript = verdict.stop_reason_in_transcript
            reason_in_transcript = verdict.reason_in_transcript
            overrode_other_block = verdict.overrode_other_block
            note = verdict.note
        else:
            handler_ran = 0
            note = verdict.note

    return Record(
        name=case.name,
        event=case.event,
        event_fired=event_fired,
        handler_ran=handler_ran,
        matcher_honored=matcher_honored,
        goes_idle=goes_idle,
        continues_working=continues_working,
        feedback=feedback,
        stop_reason_in_transcript=stop_reason_in_transcript,
        reason_in_transcript=reason_in_transcript,
        overrode_other_block=overrode_other_block,
        team_name_used=team_name_used,
        agent_id_present=agent_id_present,
        agent_id_required=0,
        blocks_termination=blocks_termination,
        stderr_to_user=stderr_to_user,
        on_failure_honored=on_failure_honored,
        action_goes_ahead=action_goes_ahead,
        python_callback=1 if PYTHON_CALLBACK else 0,
        typescript_callback=1 if TYPESCRIPT_CALLBACK else 0,
        named_in_file_missing_rule=named,
        waits_for_server=waits,
        simulated=simulated,
        note=note,
    )


def expect(record: Record, **flags: object) -> None:
    for key, value in flags.items():
        actual = getattr(record, key)
        if actual != value:
            raise SystemExit(f"{record.name} {key}: got {actual!r}, want {value!r}")


def check(records: dict[str, Record]) -> None:
    payload = example_payload()
    if set(payload) != {
        "session_id",
        "transcript_path",
        "cwd",
        "permission_mode",
        "hook_event_name",
        "teammate_name",
        "team_name",
    }:
        raise SystemExit("example payload grew a field the page sample does not have")
    if "agent_id" in payload or payload["teammate_name"] != EXAMPLE_TEAMMATE:
        raise SystemExit("example payload drifted")
    if payload["hook_event_name"] != "TeammateIdle":
        raise SystemExit("example event name drifted")

    expect(
        records["exit2_keeps_working"],
        goes_idle=0,
        continues_working=1,
        feedback=ARTIFACT_STDERR,
        handler_ran=1,
        simulated=1,
    )
    expect(
        records["block_keeps_working"],
        goes_idle=0,
        continues_working=1,
        feedback="lint failed",
    )
    expect(records["exit0_goes_idle"], goes_idle=1, continues_working=0, feedback="")
    expect(
        records["continue_false_overrides_block"],
        goes_idle=1,
        continues_working=0,
        overrode_other_block=1,
        stop_reason_in_transcript=1,
    )
    expect(
        records["continue_false_overrides_exit2"],
        goes_idle=1,
        continues_working=0,
        overrode_other_block=1,
        stop_reason_in_transcript=1,
    )
    ignored = records["matcher_ignored"]
    expect(
        ignored,
        event_fired=1,
        handler_ran=1,
        matcher_honored=0,
        goes_idle=1,
        continues_working=0,
    )
    branched = records["script_branches_on_name"]
    expect(
        branched,
        event_fired=1,
        handler_ran=1,
        matcher_honored=0,
        goes_idle=0,
        continues_working=1,
        feedback=ARTIFACT_STDERR,
    )
    if ignored.team_name_used or branched.team_name_used:
        raise SystemExit("script branch consulted team_name")
    expect(
        records["team_name_ignored"],
        team_name_used=0,
        continues_working=1,
        goes_idle=0,
    )
    expect(
        records["agent_id_absent"],
        agent_id_present=0,
        agent_id_required=0,
        continues_working=1,
    )
    expect(
        records["prompt_default_idle"],
        goes_idle=1,
        continues_working=0,
        feedback="",
        reason_in_transcript=1,
    )
    expect(
        records["prompt_continue_on_block"],
        goes_idle=0,
        continues_working=1,
        feedback="lint red",
    )
    expect(
        records["agent_ok_false_keeps"],
        goes_idle=0,
        continues_working=1,
        feedback="lint red",
    )
    expect(
        records["same_hook_mix_unspecified"],
        simulated=0,
        handler_ran=0,
        note="not_simulated",
        goes_idle=0,
        continues_working=0,
    )
    expect(
        records["sessionend_exit2"],
        blocks_termination=0,
        stderr_to_user=1,
        continues_working=0,
        goes_idle=0,
    )
    expect(
        records["stop_continue_false"],
        continues_working=0,
        goes_idle=0,
        note="turn_ended",
    )
    expect(
        records["sdk_on_failure_ignored"],
        on_failure_honored="0",
        action_goes_ahead="1",
        continues_working=0,
        python_callback=0,
        typescript_callback=1,
        note="callback_failure",
    )
    expect(
        records["file_missing_not_named"],
        named_in_file_missing_rule=0,
        simulated=0,
        note="not_named",
    )
    expect(
        records["mcp_wait_unspecified"],
        waits_for_server="unspecified",
        simulated=0,
        note="not_named",
    )
    if records["stop_continue_false"].waits_for_server != "1":
        raise SystemExit("Stop lost the documented MCP wait example")
    if records["sessionend_exit2"].waits_for_server != "0":
        raise SystemExit("SessionEnd lost the documented no-wait example")
    if matcher_filters("TeammateIdle", "researcher"):
        raise SystemExit("TeammateIdle matcher filtered a teammate")
    if not matcher_filters("SubagentStop", "Explore"):
        raise SystemExit("SubagentStop matcher was treated as unsupported")


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
