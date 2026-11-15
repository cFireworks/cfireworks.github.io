#!/usr/bin/env python3
"""伪控制环：PostToolUseFailure 只在执行之后，也改不了错误原文。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
假六种到来：未知工具名、schema 或工具侧校验失败、权限拒绝、
用户取消正在跑的工具、工具自己抛错、MCP 工具返回错误结果。
另有一条 shell 进程没启动起来的裸失败消息。专项没给那句原文，字符串是夹具自己的。

处理器一次只挂一只。这不是 settings 里的 hook。
专项没有列出 is_interrupt 为 true 且仍然开火的案例。夹具拒绝构造这种到来。
decision: "block" 专项没写效果。夹具不把它当成改写 error，也不当成撤销失败。
"""

from __future__ import annotations

from dataclasses import dataclass

HANDLERS = frozenset(
    {
        "none",
        "exit2",
        "exit0_stderr",
        "additional_context",
        "updated_tool_output",
        "updated_mcp_tool_output",
        "decision_block",
        "prompt_ok_false",
    }
)
ACTIVE = HANDLERS - {"none"}

# 专项例子。失败的 npm test。没有 tool_response。
EXAMPLE_COMMAND = "npm test"
EXAMPLE_DESCRIPTION = "Run test suite"
EXAMPLE_ERROR = "Exit code 1\nError: Cannot find module 'express'"
EXAMPLE_DURATION_MS = 4187
# 专项决策节的例子句子。
EXAMPLE_CONTEXT = "Additional information about the failure for Claude"
# exit 2 的 stderr 是夹具自己的。页上只写 Shows stderr to Claude。
EXIT2_STDERR = "这类测试失败先看 lockfile"
EXIT0_STDERR = "exit 0 的 stderr 模型看不见"
# MCP 的错误原文，专项没给例子。不当成稳定 schema。
MCP_TOOL = "mcp__example__check"
MCP_ERROR = "fixture mcp error result"
MCP_SERVER = {"name": "example", "source": "project"}
# 裸失败消息。专项没引用这句，只说可以没有 Exit code 行。
BARE_ERROR = "fixture: shell process did not start"
# prompt 钩子的 reason。页上没给固定句子。
PROMPT_REASON = "fixture prompt reason"


@dataclass(frozen=True)
class Call:
    kind: str
    pre_fires: bool
    failure_fires: bool
    tool_use_error: bool
    tool_name: str
    error: str
    is_interrupt: bool
    duration_ms: int | None
    mcp_server: dict | None
    cancel_running: bool


UNKNOWN = Call(
    kind="unknown_tool",
    pre_fires=False,
    failure_fires=False,
    tool_use_error=True,
    tool_name="NotATool",
    error="",
    is_interrupt=False,
    duration_ms=None,
    mcp_server=None,
    cancel_running=False,
)
SCHEMA = Call(
    kind="schema_validation",
    pre_fires=False,
    failure_fires=False,
    tool_use_error=True,
    tool_name="Bash",
    error="",
    is_interrupt=False,
    duration_ms=None,
    mcp_server=None,
    cancel_running=False,
)
PERMISSION = Call(
    kind="permission_deny",
    pre_fires=True,
    failure_fires=False,
    tool_use_error=False,
    tool_name="Bash",
    error="",
    is_interrupt=False,
    duration_ms=None,
    mcp_server=None,
    cancel_running=False,
)
CANCEL = Call(
    kind="user_cancel_running",
    pre_fires=True,
    failure_fires=False,
    tool_use_error=False,
    tool_name="Bash",
    error="",
    is_interrupt=False,
    duration_ms=None,
    mcp_server=None,
    cancel_running=True,
)
THREW = Call(
    kind="tool_threw",
    pre_fires=True,
    failure_fires=True,
    tool_use_error=False,
    tool_name="Bash",
    error=EXAMPLE_ERROR,
    is_interrupt=False,
    duration_ms=EXAMPLE_DURATION_MS,
    mcp_server=None,
    cancel_running=False,
)
MCP = Call(
    kind="mcp_error_result",
    pre_fires=True,
    failure_fires=True,
    tool_use_error=False,
    tool_name=MCP_TOOL,
    error=MCP_ERROR,
    is_interrupt=False,
    duration_ms=None,
    mcp_server=MCP_SERVER,
    cancel_running=False,
)
BARE = Call(
    kind="shell_not_started",
    pre_fires=True,
    failure_fires=True,
    tool_use_error=False,
    tool_name="Bash",
    error=BARE_ERROR,
    is_interrupt=False,
    duration_ms=None,
    mcp_server=None,
    cancel_running=False,
)


def matcher_hits(matcher: str, tool_name: str) -> bool:
    """空 matcher 对上每一次。非空只按 `|` 切开，整段相等。

    参考页写多数事件也接受逗号。夹具不模拟逗号，也不模拟正则。
    """
    if matcher == "":
        return True
    parts = [part.strip() for part in matcher.split("|")]
    return tool_name in parts


def matcher_label(matcher: str) -> str:
    if matcher == "":
        return "empty"
    return matcher


def exit_code_line(error: str) -> str:
    """只认首行 Exit code N。其余当展示文本，不拆成字段。"""
    if not error:
        return ""
    first = error.split("\n", 1)[0]
    prefix = "Exit code "
    if not first.startswith(prefix):
        return ""
    number = first[len(prefix) :]
    if number.isdigit():
        return first
    return ""


def handler_output(handler: str, continue_on_block: bool) -> tuple[int, dict | None, str]:
    """返回退出码、JSON、stderr。误用的改写字段留在 JSON 里，给断言去读。"""
    del continue_on_block
    if handler == "exit2":
        return 2, None, EXIT2_STDERR
    if handler == "exit0_stderr":
        return 0, None, EXIT0_STDERR
    if handler == "additional_context":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUseFailure",
                "additionalContext": EXAMPLE_CONTEXT,
            },
        }, ""
    if handler == "updated_tool_output":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUseFailure",
                "updatedToolOutput": {"stdout": "[redacted]", "stderr": ""},
            },
        }, ""
    if handler == "updated_mcp_tool_output":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUseFailure",
                "updatedMCPToolOutput": {"content": "[redacted]"},
            },
        }, ""
    if handler == "decision_block":
        return 0, {"decision": "block", "reason": "fixture block reason"}, ""
    if handler == "prompt_ok_false":
        return 0, {"ok": False, "reason": PROMPT_REASON}, ""
    raise SystemExit(f"not a PostToolUseFailure handler {handler}")


def read_context(payload: dict | None) -> str:
    """只认文档形状：hookEventName 为 PostToolUseFailure，且 additionalContext 是非空字符串。"""
    if not isinstance(payload, dict):
        return ""
    nested = payload.get("hookSpecificOutput")
    if not isinstance(nested, dict):
        return ""
    if nested.get("hookEventName") != "PostToolUseFailure":
        return ""
    text = nested.get("additionalContext")
    if isinstance(text, str):
        return text
    return ""


def error_rewritten(payload: dict | None) -> bool:
    """失败原文改不了。updatedToolOutput、updatedMCPToolOutput、block 都不算改写成功。"""
    del payload
    return False


def failure_undone(code: int, payload: dict | None) -> bool:
    """失败已经成立。exit 2 和任何 JSON 都不撤销。"""
    del code, payload
    return False


@dataclass(frozen=True)
class Record:
    name: str
    kind: str
    handler: str
    matcher: str
    tool: str
    pre_fired: int
    failure_fired: int
    handler_ran: int
    tool_use_error: int
    has_error: int
    failure_input_has_tool_response: int
    has_mcp_server: int
    failed_still: int
    stderr_for_model: int
    context_attached: int
    error_rewritten: int
    rewrite_accepted: int
    block_treated_as_rewrite: int
    block_treated_as_undo: int
    block_specified: int
    interrupt_on_tool_result: int
    prompt_reason_as_tool_error: int
    turn_continues: int
    continue_on_block_honored: int
    first_line_exit: str
    error_text: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"kind={self.kind}",
                f"handler={self.handler}",
                f"matcher={self.matcher}",
                f"tool={self.tool}",
                f"pre_fired={self.pre_fired}",
                f"failure_fired={self.failure_fired}",
                f"handler_ran={self.handler_ran}",
                f"tool_use_error={self.tool_use_error}",
                f"has_error={self.has_error}",
                f"failure_input_has_tool_response={self.failure_input_has_tool_response}",
                f"has_mcp_server={self.has_mcp_server}",
                f"failed_still={self.failed_still}",
                f"stderr_for_model={self.stderr_for_model}",
                f"context_attached={self.context_attached}",
                f"error_rewritten={self.error_rewritten}",
                f"rewrite_accepted={self.rewrite_accepted}",
                f"block_treated_as_rewrite={self.block_treated_as_rewrite}",
                f"block_treated_as_undo={self.block_treated_as_undo}",
                f"block_specified={self.block_specified}",
                f"interrupt_on_tool_result={self.interrupt_on_tool_result}",
                f"prompt_reason_as_tool_error={self.prompt_reason_as_tool_error}",
                f"turn_continues={self.turn_continues}",
                f"continue_on_block_honored={self.continue_on_block_honored}",
                f"first_line_exit={self.first_line_exit or '-'}",
            ]
        )


def settle(
    name: str,
    call: Call,
    handler: str,
    matcher: str = "",
    continue_on_block: bool = False,
) -> Record:
    """一次调用，一只处理器。没开火的钩，碰不到 error，也改不了没发生的失败。"""
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if call.kind not in {
        "unknown_tool",
        "schema_validation",
        "permission_deny",
        "user_cancel_running",
        "tool_threw",
        "mcp_error_result",
        "shell_not_started",
    }:
        raise SystemExit(f"unknown kind {call.kind}")
    if call.is_interrupt and call.failure_fires:
        raise SystemExit("section does not list an abort that still fires")
    if call.cancel_running and call.failure_fires:
        raise SystemExit("cancelling a running tool fired PostToolUseFailure")
    if handler == "prompt_ok_false" and not call.failure_fires:
        raise SystemExit("prompt hook ran without the failure event")

    common = dict(
        name=name,
        kind=call.kind,
        handler=handler,
        matcher=matcher_label(matcher),
        tool=call.tool_name,
        pre_fired=1 if call.pre_fires else 0,
        failure_fired=1 if call.failure_fires else 0,
        tool_use_error=1 if call.tool_use_error else 0,
        interrupt_on_tool_result=1 if call.cancel_running else 0,
        block_treated_as_rewrite=0,
        block_treated_as_undo=0,
        # 专项决策节没有写 block。这个 0 表示「没规定」，不是测到了运行时。
        block_specified=0,
        failure_input_has_tool_response=0,
    )

    if not call.failure_fires or handler == "none" or not matcher_hits(matcher, call.tool_name):
        error_text = call.error if call.failure_fires else ""
        return Record(
            handler_ran=0,
            has_error=1 if call.failure_fires and call.error else 0,
            has_mcp_server=1 if call.failure_fires and call.mcp_server else 0,
            failed_still=1 if call.failure_fires else 0,
            stderr_for_model=0,
            context_attached=0,
            error_rewritten=0,
            rewrite_accepted=0,
            prompt_reason_as_tool_error=0,
            turn_continues=0,
            continue_on_block_honored=0,
            first_line_exit=exit_code_line(error_text),
            error_text=error_text,
            **common,
        )

    code, payload, stderr = handler_output(handler, continue_on_block)
    if error_rewritten(payload) or failure_undone(code, payload):
        raise SystemExit("PostToolUseFailure rewrote or undid the failure")
    context = read_context(payload)
    # exit 0 的 stderr 模型看不见。exit 2 把 stderr 交给模型，失败仍成立。
    stderr_for_model = 1 if code == 2 and stderr else 0
    if code == 2 and payload is not None:
        raise SystemExit("exit 2 fixture mixed in JSON")
    if handler == "exit2" and not stderr:
        raise SystemExit("exit 2 fixture lost its stderr")
    if handler == "exit0_stderr" and (code != 0 or not stderr):
        raise SystemExit("exit 0 stderr fixture drifted")
    prompt = handler == "prompt_ok_false"
    # 两档 continueOnBlock 都走同一句：reason 作为 tool error，回合继续。
    if prompt and not isinstance(payload, dict):
        raise SystemExit("prompt fixture lost its payload")
    if prompt and payload.get("ok") is not False:
        raise SystemExit("prompt fixture was not ok false")
    return Record(
        handler_ran=1,
        has_error=1 if call.error else 0,
        has_mcp_server=1 if call.mcp_server else 0,
        failed_still=1,
        stderr_for_model=stderr_for_model,
        context_attached=1 if context else 0,
        error_rewritten=0,
        rewrite_accepted=0,
        prompt_reason_as_tool_error=1 if prompt else 0,
        turn_continues=1 if prompt else 0,
        continue_on_block_honored=0,
        first_line_exit=exit_code_line(call.error),
        error_text=call.error,
        **common,
    )


def printed_records() -> list[Record]:
    return [
        settle("unknown_tool", UNKNOWN, "additional_context"),
        settle("schema_validation", SCHEMA, "exit2"),
        settle("permission_deny", PERMISSION, "exit2"),
        settle("user_cancel_running", CANCEL, "additional_context"),
        settle("tool_threw_exit2", THREW, "exit2"),
        settle("tool_threw_exit0_stderr", THREW, "exit0_stderr"),
        settle("tool_threw_context", THREW, "additional_context"),
        settle("tool_threw_updated", THREW, "updated_tool_output"),
        settle("tool_threw_block", THREW, "decision_block"),
        settle("tool_threw_prompt_off", THREW, "prompt_ok_false", continue_on_block=False),
        settle("tool_threw_prompt_on", THREW, "prompt_ok_false", continue_on_block=True),
        settle("tool_threw_matcher_miss", THREW, "additional_context", matcher="Edit|Write"),
        settle("mcp_error_updated", MCP, "updated_mcp_tool_output"),
        settle("shell_not_started", BARE, "additional_context"),
        settle("tool_threw_none", THREW, "none"),
    ]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["unknown_tool"],
        kind="unknown_tool",
        pre_fired=0,
        failure_fired=0,
        handler_ran=0,
        tool_use_error=1,
        has_error=0,
        failed_still=0,
        error_rewritten=0,
        context_attached=0,
    )
    expect(
        records["schema_validation"],
        kind="schema_validation",
        pre_fired=0,
        failure_fired=0,
        handler_ran=0,
        tool_use_error=1,
        has_error=0,
        stderr_for_model=0,
        failed_still=0,
    )
    expect(
        records["permission_deny"],
        kind="permission_deny",
        pre_fired=1,
        failure_fired=0,
        handler_ran=0,
        tool_use_error=0,
        has_error=0,
        failed_still=0,
        stderr_for_model=0,
        interrupt_on_tool_result=0,
    )
    expect(
        records["user_cancel_running"],
        kind="user_cancel_running",
        pre_fired=1,
        failure_fired=0,
        handler_ran=0,
        tool_use_error=0,
        interrupt_on_tool_result=1,
        has_error=0,
        context_attached=0,
        failure_input_has_tool_response=0,
    )
    expect(
        records["tool_threw_exit2"],
        kind="tool_threw",
        handler="exit2",
        tool="Bash",
        pre_fired=1,
        failure_fired=1,
        handler_ran=1,
        has_error=1,
        failure_input_has_tool_response=0,
        failed_still=1,
        stderr_for_model=1,
        context_attached=0,
        error_rewritten=0,
        rewrite_accepted=0,
        first_line_exit="Exit code 1",
    )
    if records["tool_threw_exit2"].error_text != EXAMPLE_ERROR:
        raise SystemExit("exit 2 rewrote the documented error")
    expect(
        records["tool_threw_exit0_stderr"],
        handler="exit0_stderr",
        failure_fired=1,
        handler_ran=1,
        failed_still=1,
        stderr_for_model=0,
        error_rewritten=0,
    )
    context = records["tool_threw_context"]
    expect(
        context,
        handler="additional_context",
        failure_fired=1,
        handler_ran=1,
        has_error=1,
        failure_input_has_tool_response=0,
        failed_still=1,
        context_attached=1,
        error_rewritten=0,
        stderr_for_model=0,
        first_line_exit="Exit code 1",
    )
    if context.error_text != EXAMPLE_ERROR:
        raise SystemExit("additionalContext rewrote the documented error")
    if THREW.duration_ms != EXAMPLE_DURATION_MS or THREW.is_interrupt:
        raise SystemExit("npm test fixture drifted from the documented example")
    expect(
        records["tool_threw_updated"],
        handler="updated_tool_output",
        failure_fired=1,
        handler_ran=1,
        failed_still=1,
        error_rewritten=0,
        rewrite_accepted=0,
        context_attached=0,
    )
    if records["tool_threw_updated"].error_text != EXAMPLE_ERROR:
        raise SystemExit("updatedToolOutput rewrote the documented error")
    expect(
        records["tool_threw_block"],
        handler="decision_block",
        failure_fired=1,
        handler_ran=1,
        failed_still=1,
        error_rewritten=0,
        block_treated_as_rewrite=0,
        block_treated_as_undo=0,
        block_specified=0,
        prompt_reason_as_tool_error=0,
        turn_continues=0,
    )
    if records["tool_threw_block"].error_text != EXAMPLE_ERROR:
        raise SystemExit("decision block rewrote the documented error")
    for name in ("tool_threw_prompt_off", "tool_threw_prompt_on"):
        expect(
            records[name],
            handler="prompt_ok_false",
            failure_fired=1,
            handler_ran=1,
            failed_still=1,
            error_rewritten=0,
            prompt_reason_as_tool_error=1,
            turn_continues=1,
            continue_on_block_honored=0,
        )
        if records[name].error_text != EXAMPLE_ERROR:
            raise SystemExit("prompt hook was treated as an error rewrite")
    expect(
        records["tool_threw_matcher_miss"],
        matcher="Edit|Write",
        tool="Bash",
        failure_fired=1,
        handler_ran=0,
        context_attached=0,
        failed_still=1,
        error_rewritten=0,
    )
    mcp = records["mcp_error_updated"]
    expect(
        mcp,
        kind="mcp_error_result",
        tool=MCP_TOOL,
        pre_fired=1,
        failure_fired=1,
        handler_ran=1,
        has_error=1,
        has_mcp_server=1,
        failure_input_has_tool_response=0,
        failed_still=1,
        error_rewritten=0,
        rewrite_accepted=0,
        tool_use_error=0,
        first_line_exit="",
    )
    if mcp.error_text != MCP_ERROR:
        raise SystemExit("updatedMCPToolOutput rewrote the mcp error")
    if MCP.mcp_server != MCP_SERVER:
        raise SystemExit("mcp_server fixture drifted from name and source")
    bare = records["shell_not_started"]
    expect(
        bare,
        kind="shell_not_started",
        failure_fired=1,
        handler_ran=1,
        has_error=1,
        context_attached=1,
        error_rewritten=0,
        failed_still=1,
        first_line_exit="",
        failure_input_has_tool_response=0,
    )
    if bare.error_text != BARE_ERROR or bare.error_text.startswith("Exit code "):
        raise SystemExit("bare failure fixture grew an exit-code line")
    expect(
        records["tool_threw_none"],
        handler="none",
        failure_fired=1,
        handler_ran=0,
        has_error=1,
        failed_still=1,
        error_rewritten=0,
        context_attached=0,
        stderr_for_model=0,
    )

    if any(row.failure_input_has_tool_response != 0 for row in records.values()):
        raise SystemExit("a failure input carried tool_response")
    if any(row.error_rewritten != 0 or row.rewrite_accepted != 0 for row in records.values()):
        raise SystemExit("a handler rewrote the error")
    if any(row.block_specified != 0 for row in records.values()):
        raise SystemExit("block was treated as specified")
    if any(row.block_treated_as_rewrite != 0 or row.block_treated_as_undo != 0 for row in records.values()):
        raise SystemExit("block was treated as a rewrite or an undo")
    if any(row.continue_on_block_honored != 0 for row in records.values()):
        raise SystemExit("continueOnBlock changed the prompt outcome")
    fired = [row for row in records.values() if row.failure_fired]
    if any(row.failed_still != 1 for row in fired):
        raise SystemExit("a fired failure was undone")
    quiet = [row for row in records.values() if not row.failure_fired]
    if any(row.handler_ran or row.failed_still or row.stderr_for_model or row.context_attached for row in quiet):
        raise SystemExit("a handler ran before the tool failed in this event")
    if records["unknown_tool"].pre_fired or records["schema_validation"].pre_fired:
        raise SystemExit("validation fired PreToolUse")
    if not records["permission_deny"].pre_fired or records["permission_deny"].failure_fired:
        raise SystemExit("permission denial split drifted")

    code, payload, stderr = handler_output("exit2", False)
    if code != 2 or payload is not None or stderr != EXIT2_STDERR:
        raise SystemExit("exit 2 fixture drifted")
    if error_rewritten(payload) or failure_undone(code, payload):
        raise SystemExit("exit 2 undid the failure")
    ctx_code, ctx_payload, ctx_stderr = handler_output("additional_context", False)
    if ctx_code != 0 or ctx_stderr or read_context(ctx_payload) != EXAMPLE_CONTEXT:
        raise SystemExit("additionalContext fixture drifted")
    if error_rewritten(ctx_payload):
        raise SystemExit("additionalContext was treated as a rewrite")
    updated_code, updated_payload, _updated_stderr = handler_output("updated_tool_output", False)
    nested = updated_payload.get("hookSpecificOutput") if isinstance(updated_payload, dict) else None
    if updated_code != 0 or not isinstance(nested, dict) or "updatedToolOutput" not in nested:
        raise SystemExit("updatedToolOutput fixture drifted")
    if error_rewritten(updated_payload):
        raise SystemExit("updatedToolOutput was accepted")
    mcp_code, mcp_payload, _mcp_stderr = handler_output("updated_mcp_tool_output", False)
    mcp_nested = mcp_payload.get("hookSpecificOutput") if isinstance(mcp_payload, dict) else None
    if mcp_code != 0 or not isinstance(mcp_nested, dict) or "updatedMCPToolOutput" not in mcp_nested:
        raise SystemExit("updatedMCPToolOutput fixture drifted")
    if error_rewritten(mcp_payload):
        raise SystemExit("updatedMCPToolOutput was accepted")
    block_code, block_payload, _block_stderr = handler_output("decision_block", False)
    if block_code != 0 or not isinstance(block_payload, dict) or block_payload.get("decision") != "block":
        raise SystemExit("decision block fixture drifted")
    if error_rewritten(block_payload) or failure_undone(block_code, block_payload):
        raise SystemExit("decision block was given an unspecified effect")

    if not matcher_hits("", "Bash") or not matcher_hits("Bash", "Bash"):
        raise SystemExit("Bash matcher missed Bash")
    if matcher_hits("Bash", "Edit") or matcher_hits("Edit|Write", "Bash"):
        raise SystemExit("matcher caught the wrong tool")
    if not matcher_hits("Edit|Write", "Write"):
        raise SystemExit("pipe matcher drifted")
    if exit_code_line(EXAMPLE_ERROR) != "Exit code 1":
        raise SystemExit("documented first line was not read")
    if exit_code_line(BARE_ERROR):
        raise SystemExit("bare failure was parsed as an exit code")
    truncated = "Exit code 1\n... [12 characters truncated] ...\nCommand timed out after 2m 0s"
    if exit_code_line(truncated) != "Exit code 1":
        raise SystemExit("truncation marker was parsed as schema")
    if "characters truncated" in exit_code_line(truncated):
        raise SystemExit("display text leaked into the exit-code key")

    try:
        settle("bad", THREW, "grant")
    except SystemExit as exc:
        if "unknown handler" not in str(exc):
            raise
    else:
        raise SystemExit("unknown handler was accepted")
    try:
        settle(
            "bad_interrupt",
            Call(
                kind="tool_threw",
                pre_fires=True,
                failure_fires=True,
                tool_use_error=False,
                tool_name="Bash",
                error="aborted",
                is_interrupt=True,
                duration_ms=None,
                mcp_server=None,
                cancel_running=False,
            ),
            "none",
        )
    except SystemExit as exc:
        if "still fires" not in str(exc):
            raise
    else:
        raise SystemExit("an unspecified interrupt firing was accepted")


def main() -> None:
    rows = printed_records()
    records = {row.name: row for row in rows}
    if len(records) != len(rows):
        raise SystemExit("duplicate case name")
    check(records)
    for row in rows:
        print(row.line())
    print("result=pass")


if __name__ == "__main__":
    main()
