#!/usr/bin/env python3
"""伪控制环：PermissionDenied 不是放行，retry 也不改判。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
假五种到来：手动拒绝弹窗、PreToolUse 拦住、deny 规则命中、
auto 分类器给出裁决后拒绝、分类器没有裁决就拒绝。
另有一条分类器模型不可用，reason 用专项的固定文本。
这条只断言会开火。retry 对这句固定文本是忽略还是收下，专项没有写。

处理器一次只挂一只。这不是 settings 里的 hook。
人手在 Recently blocked 按 r，是另一条路，夹具不模拟。
"""

from __future__ import annotations

from dataclasses import dataclass

HANDLERS = frozenset(
    {
        "none",
        "pd_exit2",
        "pd_retry_true",
        "pd_retry_false",
        "pd_no_json",
        "pd_permission_decision_allow",
        "pd_behavior_allow",
        "pd_decision_allow",
        "pd_audit",
        "pd_prompt_discarded",
    }
)
# 会去读输出的处理器。none 表示这次没有挂钩。
ACTIVE = HANDLERS - {"none"}
VERDICTS = frozenset({"classifier", "no_verdict", "unavailable"})
# hooks 页例子。Bash，permission 模式那一行是 auto。
EXAMPLE_COMMAND = "rm -rf /tmp/build"
EXAMPLE_DESCRIPTION = "Clean build directory"
EXAMPLE_REASON = "[Irreversible Local Destruction]"
# 无裁决。专项只规定开头。错误页破折号后的半句不拼进来。
NO_VERDICT_REASON = (
    "Auto mode could not evaluate this action and is blocking it for safety"
)
# 分类器模型不可用。专项写的固定文本。不是错误页那句 temporarily unavailable。
UNAVAILABLE_REASON = "Classifier unavailable"
# 夹具自己的 stderr。页上写 exit 2 的 stderr 被忽略。这句话不当成放行理由。
EXIT2_STDERR = "改判放行"
# 页上没有给出 retry: true 加进对话的那句原文。夹具只用旗标，不编句子。


@dataclass(frozen=True)
class Call:
    kind: str
    fires: bool
    tool_name: str
    command: str
    reason: str
    verdict: str


MANUAL = Call(
    kind="manual_deny",
    fires=False,
    tool_name="Bash",
    command=EXAMPLE_COMMAND,
    reason="",
    verdict="",
)
PRE_BLOCK = Call(
    kind="pretooluse_block",
    fires=False,
    tool_name="Bash",
    command=EXAMPLE_COMMAND,
    reason="",
    verdict="",
)
DENY_RULE = Call(
    kind="deny_rule",
    fires=False,
    tool_name="Bash",
    command=EXAMPLE_COMMAND,
    reason="",
    verdict="",
)
AUTO = Call(
    kind="auto_classifier_deny",
    fires=True,
    tool_name="Bash",
    command=EXAMPLE_COMMAND,
    reason=EXAMPLE_REASON,
    verdict="classifier",
)
NO_VERDICT = Call(
    kind="no_verdict_deny",
    fires=True,
    tool_name="Bash",
    command=EXAMPLE_COMMAND,
    reason=NO_VERDICT_REASON,
    verdict="no_verdict",
)
UNAVAILABLE = Call(
    kind="classifier_unavailable",
    fires=True,
    tool_name="Bash",
    command=EXAMPLE_COMMAND,
    reason=UNAVAILABLE_REASON,
    verdict="unavailable",
)
# matcher 没对上时，事件仍是一次 auto 拒绝，这只处理器不跑。
# 路径是夹具自己的。例子 JSON 没有给 Edit。
AUTO_EDIT = Call(
    kind="auto_classifier_deny",
    fires=True,
    tool_name="Edit",
    command="",
    reason=EXAMPLE_REASON,
    verdict="classifier",
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


def pd_output(handler: str) -> tuple[int, dict | None, str]:
    """返回退出码、JSON、stderr。误用的放行字段留在 JSON 里，给断言去读。"""
    if handler == "pd_exit2":
        return 2, None, EXIT2_STDERR
    if handler == "pd_retry_true":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PermissionDenied",
                "retry": True,
            },
        }, ""
    if handler == "pd_retry_false":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PermissionDenied",
                "retry": False,
            },
        }, ""
    if handler in ("pd_no_json", "pd_audit"):
        return 0, None, ""
    if handler == "pd_permission_decision_allow":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PermissionDenied",
                "permissionDecision": "allow",
            },
        }, ""
    if handler == "pd_behavior_allow":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PermissionDenied",
                "decision": {"behavior": "allow"},
            },
        }, ""
    if handler == "pd_decision_allow":
        return 0, {"decision": "allow"}, ""
    if handler == "pd_prompt_discarded":
        return 0, {"ok": False, "reason": "allow it"}, ""
    raise SystemExit(f"not a PermissionDenied handler {handler}")


def read_retry(payload: dict | None) -> bool | None:
    """只认文档形状：hookSpecificOutput.hookEventName 为 PermissionDenied，且 retry 是布尔。"""
    if not isinstance(payload, dict):
        return None
    nested = payload.get("hookSpecificOutput")
    if not isinstance(nested, dict):
        return None
    if nested.get("hookEventName") != "PermissionDenied":
        return None
    retry = nested.get("retry")
    if isinstance(retry, bool):
        return retry
    return None


def denial_reversed(code: int, payload: dict | None) -> bool:
    """拒绝已经发生。exit 2、retry、以及另外两只事件的放行字段，都不改判。"""
    del code, payload
    return False


def treated_as_allow(code: int, payload: dict | None) -> bool:
    """permissionDecision、decision.behavior、顶层 decision allow，都不当成放行。"""
    del code, payload
    return False


def audit_line(call: Call) -> str:
    """只记页上点名的 tool_name、tool_input 和 reason。不写 Auto mode: 前缀。"""
    if call.tool_name == "Bash":
        tool_input = f"command={call.command}"
    else:
        tool_input = "tool_input=edit-fixture"
    return f"{call.tool_name} {tool_input} reason={call.reason}"


@dataclass(frozen=True)
class Record:
    name: str
    kind: str
    handler: str
    matcher: str
    tool: str
    pd_fired: int
    handler_ran: int
    denial_stands: int
    denial_reversed: int
    may_retry: int
    retry_ignored: int
    treated_as_allow: int
    stderr_applied: int
    model_keeps_original: int
    post_failure_fired: int
    audit_logged: int
    audit_line: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"kind={self.kind}",
                f"handler={self.handler}",
                f"matcher={self.matcher}",
                f"tool={self.tool}",
                f"pd_fired={self.pd_fired}",
                f"handler_ran={self.handler_ran}",
                f"denial_stands={self.denial_stands}",
                f"denial_reversed={self.denial_reversed}",
                f"may_retry={self.may_retry}",
                f"retry_ignored={self.retry_ignored}",
                f"treated_as_allow={self.treated_as_allow}",
                f"stderr_applied={self.stderr_applied}",
                f"model_keeps_original={self.model_keeps_original}",
                f"post_failure_fired={self.post_failure_fired}",
                f"audit_logged={self.audit_logged}",
            ]
        )


def settle(
    name: str,
    call: Call,
    handler: str,
    matcher: str = "",
) -> Record:
    """一次拒绝，一只处理器。没跑起来的钩，不改已经成立的拒绝。"""
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if call.kind not in {
        "manual_deny",
        "pretooluse_block",
        "deny_rule",
        "auto_classifier_deny",
        "no_verdict_deny",
        "classifier_unavailable",
    }:
        raise SystemExit(f"unknown kind {call.kind}")
    if call.fires and call.verdict not in VERDICTS:
        raise SystemExit(f"unknown verdict {call.verdict}")
    if not call.fires and call.verdict:
        raise SystemExit("non-firing call carried a verdict")
    if handler == "pd_retry_true" and call.verdict == "unavailable":
        raise SystemExit("retry on Classifier unavailable is not specified")

    # 权限拒绝不是 PostToolUseFailure。校验拒绝连 PreToolUse 都没有，夹具不模拟那一条。
    post_failure = 0
    denial_stands = 1
    model_keeps_original = 1

    if not call.fires or handler == "none" or not matcher_hits(matcher, call.tool_name):
        return Record(
            name=name,
            kind=call.kind,
            handler=handler,
            matcher=matcher_label(matcher),
            tool=call.tool_name,
            pd_fired=1 if call.fires else 0,
            handler_ran=0,
            denial_stands=denial_stands,
            denial_reversed=0,
            may_retry=0,
            retry_ignored=0,
            treated_as_allow=0,
            stderr_applied=0,
            model_keeps_original=model_keeps_original,
            post_failure_fired=post_failure,
            audit_logged=0,
            audit_line="",
        )

    code, payload, stderr = pd_output(handler)
    if denial_reversed(code, payload) or treated_as_allow(code, payload):
        raise SystemExit("PermissionDenied was treated as a grant")
    # prompt 和 agent 钩子的输出被丢掉。它们设不了 retry。
    if handler == "pd_prompt_discarded":
        retry = None
    else:
        retry = read_retry(payload)
    if retry is True and call.verdict == "no_verdict":
        may_retry = 0
        retry_ignored = 1
    elif retry is True and call.verdict == "classifier":
        may_retry = 1
        retry_ignored = 0
    else:
        may_retry = 0
        retry_ignored = 0
    # exit 2 的 stderr 读过，不拿来当放行，也不拿来当拒绝理由。拒绝早就成立。
    stderr_applied = 0
    if code == 2 and not stderr:
        raise SystemExit("exit 2 fixture lost its stderr")
    del stderr
    logged = handler == "pd_audit"
    return Record(
        name=name,
        kind=call.kind,
        handler=handler,
        matcher=matcher_label(matcher),
        tool=call.tool_name,
        pd_fired=1,
        handler_ran=1,
        denial_stands=denial_stands,
        denial_reversed=0,
        may_retry=may_retry,
        retry_ignored=retry_ignored,
        treated_as_allow=0,
        stderr_applied=stderr_applied,
        model_keeps_original=model_keeps_original,
        post_failure_fired=post_failure,
        audit_logged=1 if logged else 0,
        audit_line=audit_line(call) if logged else "",
    )


def printed_records() -> list[Record]:
    return [
        settle("manual_deny_retry_true", MANUAL, "pd_retry_true"),
        settle("pretooluse_block_exit2", PRE_BLOCK, "pd_exit2"),
        settle("deny_rule_behavior_allow", DENY_RULE, "pd_behavior_allow"),
        settle("auto_exit2", AUTO, "pd_exit2"),
        settle("auto_retry_true", AUTO, "pd_retry_true"),
        settle("no_verdict_retry_true", NO_VERDICT, "pd_retry_true"),
        settle("auto_retry_false", AUTO, "pd_retry_false"),
        settle("auto_no_json", AUTO, "pd_no_json"),
        settle("no_verdict_no_json", NO_VERDICT, "pd_no_json"),
        settle("no_verdict_exit2", NO_VERDICT, "pd_exit2"),
        settle("auto_permission_decision_allow", AUTO, "pd_permission_decision_allow"),
        settle("auto_behavior_allow", AUTO, "pd_behavior_allow"),
        settle("auto_decision_allow", AUTO, "pd_decision_allow"),
        settle("auto_audit", AUTO, "pd_audit"),
        settle("no_verdict_audit", NO_VERDICT, "pd_audit"),
        settle("unavailable_audit", UNAVAILABLE, "pd_audit"),
        settle("auto_prompt_discarded", AUTO, "pd_prompt_discarded"),
        settle("auto_edit_matcher_bash", AUTO_EDIT, "pd_retry_true", matcher="Bash"),
        settle("auto_none", AUTO, "none"),
    ]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["manual_deny_retry_true"],
        kind="manual_deny",
        handler="pd_retry_true",
        pd_fired=0,
        handler_ran=0,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        retry_ignored=0,
        treated_as_allow=0,
        model_keeps_original=1,
        post_failure_fired=0,
    )
    expect(
        records["pretooluse_block_exit2"],
        kind="pretooluse_block",
        handler="pd_exit2",
        pd_fired=0,
        handler_ran=0,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        treated_as_allow=0,
        stderr_applied=0,
    )
    expect(
        records["deny_rule_behavior_allow"],
        kind="deny_rule",
        handler="pd_behavior_allow",
        pd_fired=0,
        handler_ran=0,
        denial_stands=1,
        denial_reversed=0,
        treated_as_allow=0,
        may_retry=0,
    )
    expect(
        records["auto_exit2"],
        kind="auto_classifier_deny",
        handler="pd_exit2",
        pd_fired=1,
        handler_ran=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        retry_ignored=0,
        treated_as_allow=0,
        stderr_applied=0,
        model_keeps_original=1,
        post_failure_fired=0,
    )
    expect(
        records["auto_retry_true"],
        kind="auto_classifier_deny",
        handler="pd_retry_true",
        matcher="empty",
        tool="Bash",
        pd_fired=1,
        handler_ran=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=1,
        retry_ignored=0,
        treated_as_allow=0,
        model_keeps_original=1,
        post_failure_fired=0,
    )
    expect(
        records["no_verdict_retry_true"],
        kind="no_verdict_deny",
        pd_fired=1,
        handler_ran=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        retry_ignored=1,
        treated_as_allow=0,
        model_keeps_original=1,
    )
    expect(
        records["auto_retry_false"],
        handler="pd_retry_false",
        pd_fired=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        retry_ignored=0,
        model_keeps_original=1,
        treated_as_allow=0,
    )
    expect(
        records["auto_no_json"],
        handler="pd_no_json",
        pd_fired=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        retry_ignored=0,
        model_keeps_original=1,
        treated_as_allow=0,
    )
    expect(
        records["no_verdict_no_json"],
        kind="no_verdict_deny",
        handler="pd_no_json",
        pd_fired=1,
        denial_stands=1,
        may_retry=0,
        retry_ignored=0,
        model_keeps_original=1,
    )
    expect(
        records["no_verdict_exit2"],
        kind="no_verdict_deny",
        handler="pd_exit2",
        pd_fired=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        retry_ignored=0,
        stderr_applied=0,
        treated_as_allow=0,
        model_keeps_original=1,
    )
    expect(
        records["auto_permission_decision_allow"],
        handler="pd_permission_decision_allow",
        pd_fired=1,
        handler_ran=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        treated_as_allow=0,
        model_keeps_original=1,
    )
    expect(
        records["auto_behavior_allow"],
        handler="pd_behavior_allow",
        pd_fired=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        treated_as_allow=0,
    )
    expect(
        records["auto_decision_allow"],
        handler="pd_decision_allow",
        pd_fired=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        treated_as_allow=0,
        model_keeps_original=1,
    )
    auto_audit = records["auto_audit"]
    expect(
        auto_audit,
        handler="pd_audit",
        pd_fired=1,
        handler_ran=1,
        audit_logged=1,
        denial_stands=1,
        may_retry=0,
        model_keeps_original=1,
        post_failure_fired=0,
    )
    if auto_audit.audit_line != f"Bash command={EXAMPLE_COMMAND} reason={EXAMPLE_REASON}":
        raise SystemExit("classifier audit drifted from the documented example")
    if "Auto mode:" in auto_audit.audit_line:
        raise SystemExit("audit stored the notice prefix")
    no_verdict_audit = records["no_verdict_audit"]
    expect(no_verdict_audit, pd_fired=1, audit_logged=1, denial_stands=1, may_retry=0)
    if not no_verdict_audit.audit_line.endswith(f"reason={NO_VERDICT_REASON}"):
        raise SystemExit("no-verdict audit missed the documented prefix")
    if "run with --debug" in no_verdict_audit.audit_line:
        raise SystemExit("no-verdict audit copied the errors-page tail")
    unavailable = records["unavailable_audit"]
    expect(
        unavailable,
        kind="classifier_unavailable",
        pd_fired=1,
        handler_ran=1,
        audit_logged=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        retry_ignored=0,
        treated_as_allow=0,
    )
    if unavailable.audit_line != f"Bash command={EXAMPLE_COMMAND} reason={UNAVAILABLE_REASON}":
        raise SystemExit("unavailable audit drifted from the fixed text")
    if "temporarily unavailable" in unavailable.audit_line:
        raise SystemExit("unavailable audit copied the user-facing sentence")
    expect(
        records["auto_prompt_discarded"],
        handler="pd_prompt_discarded",
        pd_fired=1,
        handler_ran=1,
        denial_stands=1,
        denial_reversed=0,
        may_retry=0,
        retry_ignored=0,
        treated_as_allow=0,
        model_keeps_original=1,
    )
    expect(
        records["auto_edit_matcher_bash"],
        kind="auto_classifier_deny",
        tool="Edit",
        matcher="Bash",
        pd_fired=1,
        handler_ran=0,
        may_retry=0,
        denial_stands=1,
        denial_reversed=0,
        treated_as_allow=0,
    )
    expect(
        records["auto_none"],
        handler="none",
        pd_fired=1,
        handler_ran=0,
        denial_stands=1,
        may_retry=0,
        audit_logged=0,
        model_keeps_original=1,
    )

    if any(row.denial_reversed != 0 or row.treated_as_allow != 0 for row in records.values()):
        raise SystemExit("a hook reversed a denial")
    if any(row.denial_stands != 1 or row.model_keeps_original != 1 for row in records.values()):
        raise SystemExit("a hook cleared the original rejection")
    if any(row.post_failure_fired != 0 for row in records.values()):
        raise SystemExit("PostToolUseFailure fired for a permission denial")
    if any(row.stderr_applied != 0 for row in records.values()):
        raise SystemExit("stderr was applied on PermissionDenied")
    if sum(row.may_retry for row in records.values()) != 1:
        raise SystemExit("may_retry was set outside the classifier retry case")
    if records["no_verdict_retry_true"].retry_ignored != 1:
        raise SystemExit("no-verdict retry was honored")

    code, payload, stderr = pd_output("pd_exit2")
    if code != 2 or payload is not None or stderr != EXIT2_STDERR:
        raise SystemExit("exit 2 fixture drifted")
    if denial_reversed(code, payload) or treated_as_allow(code, payload):
        raise SystemExit("exit 2 granted the call")
    retry_code, retry_payload, retry_stderr = pd_output("pd_retry_true")
    if retry_code != 0 or retry_stderr:
        raise SystemExit("retry fixture did not exit 0")
    nested = retry_payload.get("hookSpecificOutput") if isinstance(retry_payload, dict) else None
    if not isinstance(nested, dict):
        raise SystemExit("retry fixture lost hookSpecificOutput")
    if nested.get("hookEventName") != "PermissionDenied" or nested.get("retry") is not True:
        raise SystemExit("retry fixture lost the documented shape")
    if read_retry(retry_payload) is not True:
        raise SystemExit("documented retry shape was not read")
    false_code, false_payload, false_stderr = pd_output("pd_retry_false")
    if false_code != 0 or false_stderr or read_retry(false_payload) is not False:
        raise SystemExit("retry false fixture drifted")
    allow_code, allow_payload, allow_stderr = pd_output("pd_permission_decision_allow")
    if allow_code != 0 or allow_stderr or read_retry(allow_payload) is not None:
        raise SystemExit("permissionDecision was read as retry")
    allow_nested = allow_payload.get("hookSpecificOutput") if isinstance(allow_payload, dict) else None
    if not isinstance(allow_nested, dict) or allow_nested.get("permissionDecision") != "allow":
        raise SystemExit("permissionDecision fixture lost the field")
    if treated_as_allow(allow_code, allow_payload):
        raise SystemExit("permissionDecision allow granted the call")
    behavior_code, behavior_payload, _behavior_stderr = pd_output("pd_behavior_allow")
    behavior_nested = (
        behavior_payload.get("hookSpecificOutput") if isinstance(behavior_payload, dict) else None
    )
    behavior = behavior_nested.get("decision") if isinstance(behavior_nested, dict) else None
    if not isinstance(behavior, dict) or behavior.get("behavior") != "allow":
        raise SystemExit("decision.behavior fixture drifted")
    if read_retry(behavior_payload) is not None or treated_as_allow(behavior_code, behavior_payload):
        raise SystemExit("decision.behavior allow was treated as a grant")
    decision_code, decision_payload, _decision_stderr = pd_output("pd_decision_allow")
    if not isinstance(decision_payload, dict) or decision_payload.get("decision") != "allow":
        raise SystemExit("top-level decision allow fixture drifted")
    if read_retry(decision_payload) is not None or treated_as_allow(decision_code, decision_payload):
        raise SystemExit("top-level decision allow was treated as a grant")
    prompt_code, prompt_payload, _prompt_stderr = pd_output("pd_prompt_discarded")
    if prompt_code != 0 or not isinstance(prompt_payload, dict) or prompt_payload.get("ok") is not False:
        raise SystemExit("prompt fixture drifted")
    if treated_as_allow(prompt_code, prompt_payload):
        raise SystemExit("discarded prompt output granted the call")

    if not matcher_hits("", "Bash") or not matcher_hits("Bash", "Bash"):
        raise SystemExit("Bash matcher missed Bash")
    if matcher_hits("Bash", "Edit"):
        raise SystemExit("Bash matcher caught Edit")
    if not matcher_hits("Edit|Write", "Write"):
        raise SystemExit("pipe matcher drifted")
    if AUTO.reason != EXAMPLE_REASON or AUTO.command != EXAMPLE_COMMAND:
        raise SystemExit("classifier fixture drifted from the documented example")
    if not NO_VERDICT.reason.startswith(NO_VERDICT_REASON):
        raise SystemExit("no-verdict reason lost its documented prefix")
    if UNAVAILABLE.reason != UNAVAILABLE_REASON:
        raise SystemExit("unavailable reason drifted")
    if MANUAL.fires or PRE_BLOCK.fires or DENY_RULE.fires:
        raise SystemExit("a non-auto path fired PermissionDenied")
    if not AUTO.fires or not NO_VERDICT.fires or not UNAVAILABLE.fires:
        raise SystemExit("an auto denial did not fire PermissionDenied")

    try:
        settle("bad", AUTO, "pd_grant")
    except SystemExit as exc:
        if "unknown handler" not in str(exc):
            raise
    else:
        raise SystemExit("unknown handler was accepted")
    try:
        settle("bad_unavailable_retry", UNAVAILABLE, "pd_retry_true")
    except SystemExit as exc:
        if "not specified" not in str(exc):
            raise
    else:
        raise SystemExit("unspecified retry on Classifier unavailable was accepted")


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
