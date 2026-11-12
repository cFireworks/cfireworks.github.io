#!/usr/bin/env python3
"""伪控制环：用户打出的斜杠命令不走 PreToolUse 的 Skill。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
假一次打出来的 /deploy staging（slash_command，command_name=deploy），
一次 /review，一次 MCP prompt，一次 Claude 调用 Skill 工具。
处理器是 upe_exit2、upe_block_decision、upe_stdout_context、ups_exit2、
pretooluse_skill_only、upe_with_if、none。
这不是 settings 里的 hook。

ups_exit2 把 expanded 和 embedded_shell_ran 记成 0，是对官方 changelog
v2.1.299 的模拟：UserPromptSubmit 在 skill 或自定义斜杠命令展开之前跑，
拦住提示也就停掉嵌入的 shell。不是 Claude Code。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

HANDLERS = frozenset(
    {
        "none",
        "upe_exit2",
        "upe_block_decision",
        "upe_stdout_context",
        "ups_exit2",
        "pretooluse_skill_only",
        "upe_with_if",
    }
)
UPE_HANDLERS = frozenset(
    {
        "upe_exit2",
        "upe_block_decision",
        "upe_stdout_context",
        "upe_with_if",
    }
)
TYPED_KINDS = frozenset({"typed_deploy", "typed_review", "mcp_prompt"})
STDOUT_LINE = "发布前先核对目标环境"
CHECKLIST = "发布清单：先看冻结窗口，再核对目标环境。"
# 页上的例子同时带 decision block 和 additionalContext。
# 夹具在拦住时不把这段记成已送达。这是夹具的选择，不是页上的结论。
DOCS_BLOCK_WITH_CONTEXT = {
    "decision": "block",
    "reason": "This slash command is not available",
    "hookSpecificOutput": {
        "hookEventName": "UserPromptExpansion",
        "additionalContext": "Additional context for this expansion",
    },
}


@dataclass(frozen=True)
class Invocation:
    kind: str
    expansion_type: str
    command_name: str
    command_args: str
    prompt: str
    command_source: str
    embedded_shell: int
    tool_name: str


# command_source 的例子值是 plugin。夹具不靠它做决定，也不列举别的取值。
# MCP 这条的 prompt 文本是夹具自己的，不冒充页上没给的唤起语法。
# release-note 是夹具自己的命令名。
DEPLOY = Invocation(
    kind="typed_deploy",
    expansion_type="slash_command",
    command_name="deploy",
    command_args="staging",
    prompt="/deploy staging",
    command_source="plugin",
    embedded_shell=1,
    tool_name="",
)
REVIEW = Invocation(
    kind="typed_review",
    expansion_type="slash_command",
    command_name="review",
    command_args="",
    prompt="/review",
    command_source="plugin",
    embedded_shell=0,
    tool_name="",
)
MCP = Invocation(
    kind="mcp_prompt",
    expansion_type="mcp_prompt",
    command_name="release-note",
    command_args="",
    prompt="release-note",
    command_source="",
    embedded_shell=0,
    tool_name="",
)
SKILL = Invocation(
    kind="skill_tool",
    expansion_type="",
    command_name="",
    command_args="",
    prompt="",
    command_source="",
    embedded_shell=0,
    tool_name="Skill",
)


def pretooluse_sees(kind: str) -> bool:
    """打出来的命令不算工具调用。只有 Skill 工具那条路才看见。"""
    return kind == "skill_tool"


def matcher_hits(matcher: str, value: str) -> bool:
    """空 matcher 对上每一次。非空只按 `|` 切开，整段相等。

    参考页写多数事件也接受逗号。夹具不模拟逗号，也不模拟正则。
    """
    if matcher == "":
        return True
    parts = [part.strip() for part in matcher.split("|")]
    return value in parts


def matcher_label(matcher: str, used: bool) -> str:
    if not used:
        return "na"
    if matcher == "":
        return "empty"
    return matcher


def expansion_stopped(code: int, payload: dict | None) -> bool:
    """exit 2 或顶层 decision block 才拦住展开。

    continue、systemMessage、单独的 reason 不读。
    """
    if code == 2:
        return True
    if isinstance(payload, dict) and payload.get("decision") == "block":
        return True
    return False


def nested_additional(payload: dict | None) -> str:
    """只认 hookSpecificOutput 里、hookEventName 为 UserPromptExpansion 的那段。"""
    if not isinstance(payload, dict):
        return ""
    nested = payload.get("hookSpecificOutput")
    if not isinstance(nested, dict):
        return ""
    if nested.get("hookEventName") != "UserPromptExpansion":
        return ""
    text = nested.get("additionalContext")
    if isinstance(text, str) and text:
        return text
    return ""


def delivered_context(blocked: bool, payload: dict | None, stdout: str) -> tuple[int, int, str]:
    """放行时把两条通道分开记。拦住时不记注入。

    一条真实 command hook 的 stdout 要么是纯文本，要么是一份 JSON。
    夹具把纯文本 stdout 和 additionalContext 分成两个字段，用来断言各自会到。
    不是说同一次 stdout 里又有纯文本又有 JSON。
    """
    if blocked:
        return 0, 0, ""
    extra = nested_additional(payload)
    plain = stdout.strip()
    parts: list[str] = []
    if plain:
        parts.append(plain)
    if extra:
        parts.append(extra)
    return (1 if plain else 0), (1 if extra else 0), "\n".join(parts)


def upe_output(handler: str) -> tuple[int, dict | None, str]:
    """返回退出码、JSON、纯文本通道。upe_with_if 若真跑起来会 exit 2。"""
    if handler in ("upe_exit2", "upe_with_if"):
        return 2, None, ""
    if handler == "upe_block_decision":
        return 0, {
            "decision": "block",
            "reason": "没有批准文件，命令不展开",
        }, ""
    if handler == "upe_stdout_context":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptExpansion",
                "additionalContext": CHECKLIST,
            }
        }, STDOUT_LINE
    raise SystemExit(f"not a UserPromptExpansion handler {handler}")


def ups_output(handler: str) -> tuple[int, dict | None]:
    if handler == "ups_exit2":
        return 2, None
    return 0, None


def pre_output(handler: str) -> int:
    """PreToolUse 这一刀只用 exit 2。不读 permissionDecision。"""
    if handler == "pretooluse_skill_only":
        return 2
    return 0


@dataclass(frozen=True)
class Record:
    name: str
    kind: str
    handler: str
    matcher: str
    if_set: int
    upe_fired: int
    ups_fired: int
    pretooluse_fired: int
    expanded: int
    model_saw_prompt: int
    embedded_shell_ran: int
    tool_blocked: int
    model_has_stdout: int
    model_has_additional: int
    model_context: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"kind={self.kind}",
                f"handler={self.handler}",
                f"matcher={self.matcher}",
                f"if_set={self.if_set}",
                f"upe_fired={self.upe_fired}",
                f"ups_fired={self.ups_fired}",
                f"pretooluse_fired={self.pretooluse_fired}",
                f"expanded={self.expanded}",
                f"model_saw_prompt={self.model_saw_prompt}",
                f"embedded_shell_ran={self.embedded_shell_ran}",
                f"tool_blocked={self.tool_blocked}",
                f"model_has_stdout={self.model_has_stdout}",
                f"model_has_additional={self.model_has_additional}",
            ]
        )


def _record(
    name: str,
    inv: Invocation,
    handler: str,
    matcher_text: str,
    if_set: int,
    *,
    upe_fired: int = 0,
    ups_fired: int = 0,
    pretooluse_fired: int = 0,
    expanded: int = 0,
    model_saw_prompt: int = 0,
    embedded_shell_ran: int = 0,
    tool_blocked: int = 0,
    model_has_stdout: int = 0,
    model_has_additional: int = 0,
    model_context: str = "",
) -> Record:
    return Record(
        name=name,
        kind=inv.kind,
        handler=handler,
        matcher=matcher_text,
        if_set=if_set,
        upe_fired=upe_fired,
        ups_fired=ups_fired,
        pretooluse_fired=pretooluse_fired,
        expanded=expanded,
        model_saw_prompt=model_saw_prompt,
        embedded_shell_ran=embedded_shell_ran,
        tool_blocked=tool_blocked,
        model_has_stdout=model_has_stdout,
        model_has_additional=model_has_additional,
        model_context=model_context,
    )


def expanded_view(inv: Invocation) -> tuple[int, int, int]:
    """展开发生。模型看见展开后的提示。shell 只在这条夹具带了 ! 时才跑。"""
    return 1, 1, inv.embedded_shell


def settle(
    name: str,
    inv: Invocation,
    handler: str,
    matcher: str = "",
    if_set: bool = False,
) -> Record:
    """一只处理器挂在这一次调用上。没跑起来的闸，不改变这条路的默认结局。"""
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if inv.kind not in TYPED_KINDS and inv.kind != "skill_tool":
        raise SystemExit(f"unknown kind {inv.kind}")
    flag = 1 if if_set else 0
    uses_matcher = handler in UPE_HANDLERS or handler == "pretooluse_skill_only"
    label = matcher_label(matcher, uses_matcher)
    base = dict(name=name, inv=inv, handler=handler, matcher_text=label, if_set=flag)

    if inv.kind == "skill_tool":
        # 模型调用 Skill。UserPromptExpansion 不开火。
        fired = (
            handler == "pretooluse_skill_only"
            and not if_set
            and matcher_hits(matcher, inv.tool_name)
        )
        stopped = fired and pre_output(handler) == 2
        return _record(
            **base,
            pretooluse_fired=1 if fired else 0,
            tool_blocked=1 if stopped else 0,
        )

    # 用户打出来的命令。先是 UserPromptSubmit，放行之后才展开。
    if handler == "ups_exit2":
        # v2.1.299：拦住提示，命令不跑，嵌入的 shell 也不跑。
        ups_code, ups_payload = ups_output(handler)
        if not expansion_stopped(ups_code, ups_payload):
            raise SystemExit("ups_exit2 fixture did not block")
        return _record(**base, ups_fired=1)

    if handler == "pretooluse_skill_only":
        # 直接打 /skillname 绕过 PreToolUse。展开照常发生。
        expanded, saw, shell = expanded_view(inv)
        return _record(
            **base,
            expanded=expanded,
            model_saw_prompt=saw,
            embedded_shell_ran=shell,
        )

    if handler == "none":
        expanded, saw, shell = expanded_view(inv)
        return _record(
            **base,
            expanded=expanded,
            model_saw_prompt=saw,
            embedded_shell_ran=shell,
        )

    if handler not in UPE_HANDLERS:
        raise SystemExit(f"unhandled combination {inv.kind} {handler}")

    # if 写在非工具事件上，hook 不跑。
    if if_set or not matcher_hits(matcher, inv.command_name):
        expanded, saw, shell = expanded_view(inv)
        return _record(
            **base,
            expanded=expanded,
            model_saw_prompt=saw,
            embedded_shell_ran=shell,
        )

    code, payload, stdout = upe_output(handler)
    stopped = expansion_stopped(code, payload)
    has_stdout, has_additional, context = delivered_context(stopped, payload, stdout)
    if stopped:
        return _record(
            **base,
            upe_fired=1,
            model_has_stdout=has_stdout,
            model_has_additional=has_additional,
            model_context=context,
        )
    expanded, saw, shell = expanded_view(inv)
    return _record(
        **base,
        upe_fired=1,
        expanded=expanded,
        model_saw_prompt=saw,
        embedded_shell_ran=shell,
        model_has_stdout=has_stdout,
        model_has_additional=has_additional,
        model_context=context,
    )


def printed_records() -> list[Record]:
    rows = [
        settle("typed_deploy_upe_exit2", DEPLOY, "upe_exit2", matcher="deploy"),
        settle("typed_deploy_upe_block_decision", DEPLOY, "upe_block_decision", matcher="deploy"),
        settle("typed_review_upe_exit2", REVIEW, "upe_exit2", matcher="deploy"),
        settle("typed_deploy_upe_stdout_context", DEPLOY, "upe_stdout_context", matcher=""),
        settle("typed_deploy_ups_exit2", DEPLOY, "ups_exit2"),
        settle(
            "typed_deploy_pretooluse_skill_only",
            DEPLOY,
            "pretooluse_skill_only",
            matcher="Skill",
        ),
        settle(
            "skill_tool_pretooluse_skill_only",
            SKILL,
            "pretooluse_skill_only",
            matcher="Skill",
        ),
        settle(
            "typed_deploy_upe_with_if",
            DEPLOY,
            "upe_with_if",
            matcher="deploy",
            if_set=True,
        ),
        settle("typed_deploy_none", DEPLOY, "none"),
        settle("mcp_prompt_upe_exit2", MCP, "upe_exit2", matcher="deploy"),
        settle("mcp_prompt_matched_exit2", MCP, "upe_exit2", matcher="release-note"),
        settle("mcp_prompt_stdout_context", MCP, "upe_stdout_context", matcher=""),
        settle("skill_tool_upe_exit2", SKILL, "upe_exit2", matcher="deploy"),
    ]
    return rows


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["typed_deploy_upe_exit2"],
        kind="typed_deploy",
        handler="upe_exit2",
        matcher="deploy",
        if_set=0,
        upe_fired=1,
        ups_fired=0,
        pretooluse_fired=0,
        expanded=0,
        model_saw_prompt=0,
        embedded_shell_ran=0,
        tool_blocked=0,
        model_has_stdout=0,
        model_has_additional=0,
        model_context="",
    )
    expect(
        records["typed_deploy_upe_block_decision"],
        handler="upe_block_decision",
        matcher="deploy",
        upe_fired=1,
        expanded=0,
        model_saw_prompt=0,
        embedded_shell_ran=0,
        model_has_additional=0,
        model_context="",
    )
    expect(
        records["typed_review_upe_exit2"],
        kind="typed_review",
        handler="upe_exit2",
        matcher="deploy",
        upe_fired=0,
        expanded=1,
        model_saw_prompt=1,
        embedded_shell_ran=0,
        pretooluse_fired=0,
    )
    expect(
        records["typed_deploy_upe_stdout_context"],
        handler="upe_stdout_context",
        matcher="empty",
        upe_fired=1,
        expanded=1,
        model_saw_prompt=1,
        embedded_shell_ran=1,
        model_has_stdout=1,
        model_has_additional=1,
    )
    stdout_case = records["typed_deploy_upe_stdout_context"]
    if STDOUT_LINE not in stdout_case.model_context or CHECKLIST not in stdout_case.model_context:
        raise SystemExit("allowed expansion dropped stdout or additionalContext")
    if stdout_case.model_context == STDOUT_LINE + CHECKLIST:
        raise SystemExit("the two channels were concatenated with no separator")

    expect(
        records["typed_deploy_ups_exit2"],
        handler="ups_exit2",
        matcher="na",
        ups_fired=1,
        upe_fired=0,
        expanded=0,
        model_saw_prompt=0,
        embedded_shell_ran=0,
        pretooluse_fired=0,
    )
    expect(
        records["typed_deploy_pretooluse_skill_only"],
        handler="pretooluse_skill_only",
        matcher="Skill",
        expanded=1,
        model_saw_prompt=1,
        embedded_shell_ran=1,
        pretooluse_fired=0,
        upe_fired=0,
        tool_blocked=0,
    )
    expect(
        records["skill_tool_pretooluse_skill_only"],
        kind="skill_tool",
        handler="pretooluse_skill_only",
        matcher="Skill",
        pretooluse_fired=1,
        tool_blocked=1,
        upe_fired=0,
        ups_fired=0,
        expanded=0,
        model_saw_prompt=0,
        embedded_shell_ran=0,
    )
    expect(
        records["typed_deploy_upe_with_if"],
        handler="upe_with_if",
        matcher="deploy",
        if_set=1,
        upe_fired=0,
        expanded=1,
        model_saw_prompt=1,
        embedded_shell_ran=1,
    )
    expect(
        records["typed_deploy_none"],
        handler="none",
        matcher="na",
        upe_fired=0,
        ups_fired=0,
        pretooluse_fired=0,
        expanded=1,
        model_saw_prompt=1,
        embedded_shell_ran=1,
        model_has_stdout=0,
        model_has_additional=0,
        tool_blocked=0,
    )
    expect(
        records["mcp_prompt_upe_exit2"],
        kind="mcp_prompt",
        handler="upe_exit2",
        matcher="deploy",
        upe_fired=0,
        expanded=1,
        model_saw_prompt=1,
        embedded_shell_ran=0,
    )
    expect(
        records["mcp_prompt_matched_exit2"],
        kind="mcp_prompt",
        handler="upe_exit2",
        matcher="release-note",
        upe_fired=1,
        expanded=0,
        model_saw_prompt=0,
        embedded_shell_ran=0,
    )
    expect(
        records["mcp_prompt_stdout_context"],
        kind="mcp_prompt",
        handler="upe_stdout_context",
        matcher="empty",
        upe_fired=1,
        expanded=1,
        model_saw_prompt=1,
        model_has_stdout=1,
        model_has_additional=1,
    )
    if CHECKLIST not in records["mcp_prompt_stdout_context"].model_context:
        raise SystemExit("empty matcher missed the MCP prompt")
    expect(
        records["skill_tool_upe_exit2"],
        kind="skill_tool",
        handler="upe_exit2",
        matcher="deploy",
        upe_fired=0,
        pretooluse_fired=0,
        tool_blocked=0,
        expanded=0,
        model_saw_prompt=0,
    )

    if pretooluse_sees("typed_deploy") or pretooluse_sees("mcp_prompt") or pretooluse_sees("typed_review"):
        raise SystemExit("typed command was treated as a tool call")
    if not pretooluse_sees("skill_tool"):
        raise SystemExit("Skill tool call was invisible to PreToolUse")

    if records["typed_deploy_none"].expanded != 1 or records["typed_deploy_none"].upe_fired != 0:
        raise SystemExit("silence became a gate")
    if records["typed_deploy_upe_exit2"].expanded != 0 or records["typed_deploy_upe_exit2"].model_saw_prompt != 0:
        raise SystemExit("exit 2 let the expansion through")
    if records["typed_deploy_upe_block_decision"].expanded != 0:
        raise SystemExit("decision block let the expansion through")
    if records["typed_review_upe_exit2"].expanded != 1 or records["typed_review_upe_exit2"].upe_fired != 0:
        raise SystemExit("deploy matcher blocked /review")
    if records["typed_deploy_ups_exit2"].expanded != 0 or records["typed_deploy_ups_exit2"].embedded_shell_ran != 0:
        raise SystemExit("UserPromptSubmit exit 2 still expanded or ran the shell")
    if records["typed_deploy_pretooluse_skill_only"].pretooluse_fired != 0:
        raise SystemExit("PreToolUse fired on a typed slash command")
    if records["typed_deploy_pretooluse_skill_only"].expanded != 1:
        raise SystemExit("Skill-only gate blocked the typed command")
    if records["skill_tool_pretooluse_skill_only"].pretooluse_fired != 1:
        raise SystemExit("PreToolUse missed the Skill tool call")
    if records["skill_tool_pretooluse_skill_only"].tool_blocked != 1:
        raise SystemExit("PreToolUse exit 2 did not block the Skill tool")
    if records["skill_tool_pretooluse_skill_only"].upe_fired != 0:
        raise SystemExit("UserPromptExpansion fired on a Skill tool call")
    if records["typed_deploy_upe_with_if"].upe_fired != 0 or records["typed_deploy_upe_with_if"].expanded != 1:
        raise SystemExit("if on UserPromptExpansion still ran or blocked")
    if records["skill_tool_upe_exit2"].upe_fired != 0 or records["skill_tool_upe_exit2"].tool_blocked != 0:
        raise SystemExit("expansion gate saw the Skill tool call")

    code, payload, stdout = upe_output("upe_exit2")
    if code != 2 or payload is not None or stdout:
        raise SystemExit("exit 2 fixture drifted")
    if not expansion_stopped(code, payload):
        raise SystemExit("exit 2 did not stop expansion")
    blocked_code, blocked_payload, blocked_stdout = upe_output("upe_block_decision")
    if blocked_code != 0 or blocked_stdout or not isinstance(blocked_payload, dict):
        raise SystemExit("block JSON fixture did not exit 0")
    if blocked_payload.get("decision") != "block" or not blocked_payload.get("reason"):
        raise SystemExit("block JSON fixture lost decision or reason")
    if "hookSpecificOutput" in blocked_payload:
        raise SystemExit("block JSON fixture hid context beside the decision")
    if not expansion_stopped(blocked_code, blocked_payload):
        raise SystemExit("decision block did not stop expansion")
    if_code, _if_payload, _if_stdout = upe_output("upe_with_if")
    if if_code != 2:
        raise SystemExit("if fixture would not have blocked had it run")

    context_code, context_payload, context_stdout = upe_output("upe_stdout_context")
    if context_code != 0 or not isinstance(context_payload, dict):
        raise SystemExit("stdout context fixture did not exit 0")
    if "additionalContext" in context_payload:
        raise SystemExit("additionalContext was top-level")
    if nested_additional(context_payload) != CHECKLIST:
        raise SystemExit("nested checklist drifted")
    if nested_additional({"additionalContext": CHECKLIST}) != "":
        raise SystemExit("top-level additionalContext was read")
    if nested_additional({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": CHECKLIST,
        }
    }) != "":
        raise SystemExit("UserPromptSubmit event name was accepted on this gate")
    has_stdout, has_additional, text = delivered_context(False, context_payload, context_stdout)
    if (has_stdout, has_additional) != (1, 1) or STDOUT_LINE not in text or CHECKLIST not in text:
        raise SystemExit("allowed channels did not both land")
    kept_stdout, kept_additional, kept_text = delivered_context(True, DOCS_BLOCK_WITH_CONTEXT, STDOUT_LINE)
    if (kept_stdout, kept_additional, kept_text) != (0, 0, ""):
        raise SystemExit("blocked expansion still delivered context")
    if not expansion_stopped(0, DOCS_BLOCK_WITH_CONTEXT):
        raise SystemExit("docs-shaped block JSON did not stop expansion")

    ups_code, ups_payload = ups_output("ups_exit2")
    if ups_code != 2 or ups_payload is not None:
        raise SystemExit("ups exit 2 fixture drifted")
    if pre_output("pretooluse_skill_only") != 2:
        raise SystemExit("pretooluse exit 2 fixture drifted")
    none_code, none_payload = ups_output("none")
    if (none_code, none_payload) != (0, None):
        raise SystemExit("silence on UserPromptSubmit drifted")

    plugin = settle("source_plugin", DEPLOY, "upe_exit2", matcher="deploy")
    blank = settle("source_blank", replace(DEPLOY, command_source=""), "upe_exit2", matcher="deploy")
    if (plugin.expanded, plugin.upe_fired, plugin.model_saw_prompt) != (
        blank.expanded,
        blank.upe_fired,
        blank.model_saw_prompt,
    ):
        raise SystemExit("command_source changed the gate")
    if DEPLOY.command_source != "plugin":
        raise SystemExit("slash fixture lost the documented example source")
    if DEPLOY.expansion_type != "slash_command" or DEPLOY.command_name != "deploy":
        raise SystemExit("deploy fixture drifted")
    if DEPLOY.command_args != "staging" or DEPLOY.prompt != "/deploy staging":
        raise SystemExit("deploy args drifted from the example shape")
    if MCP.expansion_type != "mcp_prompt" or MCP.command_name != "release-note":
        raise SystemExit("mcp fixture drifted")
    if SKILL.tool_name != "Skill" or SKILL.expansion_type != "":
        raise SystemExit("skill tool fixture drifted")

    if matcher_hits("deploy", "review") or matcher_hits("deploy", "deploy-prod"):
        raise SystemExit("matcher was a substring")
    if not matcher_hits("", "release-note") or not matcher_hits("deploy|review", "review"):
        raise SystemExit("empty or pipe matcher drifted")

    try:
        settle("bad", DEPLOY, "matcher_opus")
    except SystemExit as exc:
        if "unknown handler" not in str(exc):
            raise
    else:
        raise SystemExit("unknown handler was accepted")

    try:
        settle("bad_kind", replace(DEPLOY, kind="server_managed"), "none")
    except SystemExit as exc:
        if "unknown kind" not in str(exc):
            raise
    else:
        raise SystemExit("unknown kind was accepted")


def main() -> None:
    rows = printed_records()
    records = {row.name: row for row in rows}
    if len(records) != len(rows):
        raise SystemExit("duplicate case name")
    check(records)
    for row in rows:
        print(records[row.name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
