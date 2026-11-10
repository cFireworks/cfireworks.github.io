#!/usr/bin/env python3
"""伪控制环：会话中途改 settings/skills，ConfigChange 能拦进当前会话，policy 拦不住。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
假一次 project_settings、一次 skills、一次 policy_settings。
处理器是 exit2、block_decision、allow_silent、none。
另走一条 server_managed_skip：夹具里的名字，表示这次刷新不调用 hook。
另走一条 matcher 只写 project_settings|local_settings，来源却是 skills。
另走一条 local_settings 对上同一条 matcher。
另走一条给 ConfigChange 写了 if：hook 不开火。
exit 2 与顶层 decision block 的语义来自 Hooks reference 的 ConfigChange 小节。
policy_settings 上 blocking 被忽略。被拦时 ui_notice 仍是 0。
"""

from __future__ import annotations

from dataclasses import dataclass

HANDLERS = frozenset({"none", "exit2", "block_decision", "allow_silent"})
SOURCES = frozenset(
    {
        "user_settings",
        "project_settings",
        "local_settings",
        "policy_settings",
        "skills",
    }
)
NARROW = "project_settings|local_settings"


def matcher_hits(matcher: str, source: str) -> bool:
    """空 matcher 按指南那个「记下每一次变更」的例子，对上每个会开火的 source。

    非空只按 `|` 切开。参考页写多数事件也接受逗号。夹具不模拟逗号。
    """
    if source not in SOURCES:
        raise SystemExit(f"unknown source {source}")
    if matcher == "":
        return True
    parts = [part.strip() for part in matcher.split("|")]
    return source in parts


def matcher_label(matcher: str) -> str:
    if matcher == "":
        return "empty"
    return matcher


def blocks(source: str, code: int, payload: dict | None) -> bool:
    """非 policy 上，exit 2 或顶层 decision block 让新配置不进会话。

    policy_settings 上两种都忽略。continue、systemMessage、单独的 reason 不读。
    """
    if source == "policy_settings":
        return False
    if code == 2:
        return True
    if isinstance(payload, dict) and payload.get("decision") == "block":
        return True
    return False


def handler_output(handler: str) -> tuple[int, dict | None, str]:
    """返回退出码、JSON、stderr。stderr 不进入 ui_notice。"""
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if handler == "exit2":
        return 2, None, "会话中途不准把这份配置送进当前会话"
    if handler == "block_decision":
        return 0, {
            "decision": "block",
            "reason": "会话中途不准改这份配置",
            "systemMessage": "已拦截",
            "continue": False,
        }, ""
    if handler == "allow_silent":
        return 0, {
            "systemMessage": "配置已写入",
            "continue": False,
            "reason": "没有 decision 就不拦",
        }, ""
    return 0, None, ""


@dataclass(frozen=True)
class Record:
    name: str
    path: str
    source: str
    handler: str
    matcher: str
    if_set: int
    applied: int
    hook_fired: int
    ui_notice: int

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"path={self.path}",
                f"source={self.source}",
                f"handler={self.handler}",
                f"matcher={self.matcher}",
                f"if_set={self.if_set}",
                f"applied={self.applied}",
                f"hook_fired={self.hook_fired}",
                f"ui_notice={self.ui_notice}",
            ]
        )


def settle(
    name: str,
    source: str,
    handler: str,
    matcher: str = "",
    if_set: bool = False,
) -> Record:
    """会开火的配置变更。hook 没跑起来时，新配置照进会话。"""
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if source not in SOURCES:
        raise SystemExit(f"unknown source {source}")
    label = matcher_label(matcher)
    flag = 1 if if_set else 0
    if if_set or not matcher_hits(matcher, source):
        return Record(
            name=name,
            path="configchange",
            source=source,
            handler=handler,
            matcher=label,
            if_set=flag,
            applied=1,
            hook_fired=0,
            ui_notice=0,
        )
    code, payload, _stderr = handler_output(handler)
    applied = 0 if blocks(source, code, payload) else 1
    return Record(
        name=name,
        path="configchange",
        source=source,
        handler=handler,
        matcher=label,
        if_set=flag,
        applied=applied,
        hook_fired=1,
        ui_notice=0,
    )


def settle_skip() -> Record:
    """server-managed / 系统托管偏好这条刷新。夹具不调用 hook。

    source=- 不是参考页上的 matcher 值。表示这次没有 ConfigChange 输入。
    装着 exit 2 也不开火。
    """
    code, _payload, stderr = handler_output("exit2")
    if code != 2 or not stderr:
        raise SystemExit("skip path lost the installed exit 2")
    return Record(
        name="server_managed_skip",
        path="skip",
        source="-",
        handler="exit2",
        matcher="empty",
        if_set=0,
        applied=1,
        hook_fired=0,
        ui_notice=0,
    )


def printed_records() -> list[Record]:
    rows: list[Record] = []
    for source in ("project_settings", "skills", "policy_settings"):
        for handler in ("exit2", "block_decision", "allow_silent", "none"):
            rows.append(settle(f"{source}_{handler}", source, handler))
    rows.append(settle_skip())
    rows.append(
        settle(
            "skills_wrong_matcher",
            "skills",
            "exit2",
            matcher=NARROW,
        )
    )
    rows.append(
        settle(
            "local_settings_narrow_exit2",
            "local_settings",
            "exit2",
            matcher=NARROW,
        )
    )
    rows.append(
        settle(
            "project_if_skipped",
            "project_settings",
            "exit2",
            if_set=True,
        )
    )
    return rows


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    for source in ("project_settings", "skills", "policy_settings"):
        for handler in ("exit2", "block_decision", "allow_silent", "none"):
            name = f"{source}_{handler}"
            if source == "policy_settings" or handler in ("allow_silent", "none"):
                applied = 1
            else:
                applied = 0
            expect(
                records[name],
                path="configchange",
                source=source,
                handler=handler,
                matcher="empty",
                if_set=0,
                applied=applied,
                hook_fired=1,
                ui_notice=0,
            )

    expect(
        records["server_managed_skip"],
        path="skip",
        source="-",
        handler="exit2",
        matcher="empty",
        if_set=0,
        applied=1,
        hook_fired=0,
        ui_notice=0,
    )
    expect(
        records["skills_wrong_matcher"],
        path="configchange",
        source="skills",
        handler="exit2",
        matcher=NARROW,
        if_set=0,
        applied=1,
        hook_fired=0,
        ui_notice=0,
    )
    expect(
        records["local_settings_narrow_exit2"],
        path="configchange",
        source="local_settings",
        handler="exit2",
        matcher=NARROW,
        if_set=0,
        applied=0,
        hook_fired=1,
        ui_notice=0,
    )
    expect(
        records["project_if_skipped"],
        path="configchange",
        source="project_settings",
        handler="exit2",
        matcher="empty",
        if_set=1,
        applied=1,
        hook_fired=0,
        ui_notice=0,
    )

    for record in records.values():
        if record.ui_notice != 0:
            raise SystemExit(f"{record.name} surfaced a UI notice")

    if records["project_settings_exit2"].applied != 0:
        raise SystemExit("project settings exit 2 applied the change")
    if records["project_settings_block_decision"].applied != 0:
        raise SystemExit("project settings decision block applied the change")
    if records["skills_exit2"].applied != 0:
        raise SystemExit("skills exit 2 applied the change")
    if records["policy_settings_exit2"].applied != 1 or records["policy_settings_exit2"].hook_fired != 1:
        raise SystemExit("policy exit 2 was blocked or the hook did not fire")
    if (
        records["policy_settings_block_decision"].applied != 1
        or records["policy_settings_block_decision"].hook_fired != 1
    ):
        raise SystemExit("policy decision block was honored or the hook did not fire")
    if records["server_managed_skip"].hook_fired != 0 or records["server_managed_skip"].applied != 1:
        raise SystemExit("server-managed skip ran the hook or dropped the change")
    if records["project_settings_allow_silent"].applied != 1 or records["project_settings_none"].applied != 1:
        raise SystemExit("silence or a decision-less JSON blocked the change")
    if records["skills_allow_silent"].applied != 1 or records["skills_none"].applied != 1:
        raise SystemExit("skills allow path blocked the change")
    if records["policy_settings_allow_silent"].applied != 1 or records["policy_settings_none"].applied != 1:
        raise SystemExit("policy allow path dropped the change")

    exit_code, exit_payload, exit_stderr = handler_output("exit2")
    if exit_code != 2 or exit_payload is not None or not exit_stderr:
        raise SystemExit("exit 2 fixture drifted")
    if not blocks("project_settings", exit_code, exit_payload):
        raise SystemExit("exit 2 did not block project settings")
    if not blocks("skills", exit_code, exit_payload):
        raise SystemExit("exit 2 did not block skills")
    if blocks("policy_settings", exit_code, exit_payload):
        raise SystemExit("exit 2 blocked policy settings")
    if records["project_settings_exit2"].ui_notice != 0:
        raise SystemExit("exit 2 stderr became a UI notice")

    block_code, block_payload, block_stderr = handler_output("block_decision")
    if block_code != 0 or block_stderr or not isinstance(block_payload, dict):
        raise SystemExit("block JSON fixture did not exit 0")
    if block_payload.get("decision") != "block":
        raise SystemExit("block JSON fixture lost decision")
    if not block_payload.get("reason"):
        raise SystemExit("block JSON fixture lost reason")
    if not block_payload.get("systemMessage"):
        raise SystemExit("block JSON fixture lost systemMessage")
    if block_payload.get("continue") is not False:
        raise SystemExit("block JSON fixture lost continue")
    if "hookSpecificOutput" in block_payload:
        raise SystemExit("block JSON fixture hid decision inside hookSpecificOutput")
    if not blocks("skills", block_code, block_payload):
        raise SystemExit("decision block did not block skills")
    if blocks("policy_settings", block_code, block_payload):
        raise SystemExit("decision block blocked policy settings")
    if records["project_settings_block_decision"].ui_notice != 0:
        raise SystemExit("systemMessage became a UI notice")

    allow_code, allow_payload, allow_stderr = handler_output("allow_silent")
    if allow_code != 0 or allow_stderr or not isinstance(allow_payload, dict):
        raise SystemExit("allow JSON fixture did not exit 0")
    if "decision" in allow_payload:
        raise SystemExit("allow JSON fixture set decision")
    if allow_payload.get("continue") is not False:
        raise SystemExit("allow JSON fixture lost continue")
    if not allow_payload.get("systemMessage"):
        raise SystemExit("allow JSON fixture lost systemMessage")
    if blocks("project_settings", allow_code, allow_payload):
        raise SystemExit("continue or systemMessage blocked a change")
    if blocks("local_settings", allow_code, allow_payload):
        raise SystemExit("continue or systemMessage blocked local settings")

    none_code, none_payload, none_stderr = handler_output("none")
    if (none_code, none_payload, none_stderr) != (0, None, ""):
        raise SystemExit("none fixture drifted")
    if blocks("project_settings", none_code, none_payload):
        raise SystemExit("silence became a block")

    if records["skills_wrong_matcher"].hook_fired != 0 or records["skills_wrong_matcher"].applied != 1:
        raise SystemExit("wrong matcher ran the project gate against skills")
    if records["local_settings_narrow_exit2"].applied != 0 or records["local_settings_narrow_exit2"].hook_fired != 1:
        raise SystemExit("narrow matcher missed local settings")
    if not blocks("project_settings", exit_code, exit_payload):
        raise SystemExit("if-skipped path had nothing to skip")
    if records["project_if_skipped"].hook_fired != 0 or records["project_if_skipped"].applied != 1:
        raise SystemExit("if on ConfigChange still ran or blocked")

    try:
        settle("bad", "project_settings", "matcher_opus")
    except SystemExit as exc:
        if "unknown handler" not in str(exc):
            raise
    else:
        raise SystemExit("unknown handler was accepted")

    try:
        matcher_hits("", "server_managed")
    except SystemExit as exc:
        if "unknown source" not in str(exc):
            raise
    else:
        raise SystemExit("server_managed was accepted as a matcher source")


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
