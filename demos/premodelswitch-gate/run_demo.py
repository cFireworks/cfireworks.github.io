#!/usr/bin/env python3
"""伪控制环：请求切换之前 PreModelSwitch 能拦，PostModelSwitch 时已经切完。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
先走一次「用户或客户端请求切到目标模型」：Pre，没拦住才算已切完，再走 Post。
另走一条 resume 自切：Pre 不开火，模型已经是 to_model，只走 Post。
处理器是夹具，不是 settings.json 里的 hook。
exit 2、permissionDecision deny、顶层 decision block、Pre 超时，语义来自 Hooks reference。
additionalContext 只认 hookSpecificOutput。顶层同名字段不计注入。
"""

from __future__ import annotations

from dataclasses import dataclass

HANDLERS = frozenset(
    {
        "none",
        "pre_exit2",
        "pre_deny_json",
        "pre_block_decision",
        "pre_timeout_sim",
        "post_exit2",
        "post_inject_nested",
        "post_inject_toplevel",
    }
)
FROM_MODEL = "claude-sonnet-5"
TO_MODEL = "claude-opus-5"
CONTEXT = "当前会话模型是 claude-opus-5。长推理要再显式切换。"
REQUEST_PRE = {
    "hook_event_name": "PreModelSwitch",
    "from_model": FROM_MODEL,
    "to_model": TO_MODEL,
    "requested_model": "opus",
    "source": "command",
}
REQUEST_POST = {
    "hook_event_name": "PostModelSwitch",
    "from_model": FROM_MODEL,
    "to_model": TO_MODEL,
    "requested_model": "opus",
    "source": "command",
}
RESUME_POST = {
    "hook_event_name": "PostModelSwitch",
    "from_model": FROM_MODEL,
    "to_model": TO_MODEL,
    "requested_model": TO_MODEL,
    "source": "resume",
}


def nested_context(payload: dict | None, event_name: str) -> int:
    """只认 hookSpecificOutput 里的 additionalContext，且事件名要对上。"""
    if not isinstance(payload, dict):
        return 0
    nested = payload.get("hookSpecificOutput")
    if not isinstance(nested, dict):
        return 0
    if nested.get("hookEventName") != event_name:
        return 0
    text = nested.get("additionalContext")
    if isinstance(text, str) and text:
        return 1
    return 0


def pre_blocks(code: int, payload: dict | None, timed_out: bool) -> bool:
    """Pre 拦住切换的四种写法。顶层 permissionDecision 不读。

    超时丢掉输出，切换仍取消。exit 2 同样取消。
    顶层 decision block，或 hookSpecificOutput 里的 deny，也取消。
    """
    if timed_out:
        return True
    if code == 2:
        return True
    if not isinstance(payload, dict):
        return False
    if payload.get("decision") == "block":
        return True
    nested = payload.get("hookSpecificOutput")
    if not isinstance(nested, dict):
        return False
    if nested.get("hookEventName") != "PreModelSwitch":
        return False
    return nested.get("permissionDecision") == "deny"


def pre_output(handler: str) -> tuple[int, dict | None, bool]:
    """请求切换上的 Pre。返回退出码、JSON、是否按超时取消。"""
    if handler == "pre_exit2":
        return 2, None, False
    if handler == "pre_deny_json":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PreModelSwitch",
                "permissionDecision": "deny",
                "permissionDecisionReason": "未备案型号，取消切换",
            }
        }, False
    if handler == "pre_block_decision":
        return 0, {
            "decision": "block",
            "reason": "未备案型号，取消切换",
        }, False
    if handler == "pre_timeout_sim":
        # 文档：到点取消并丢掉输出。这份 allow 不该把切换放出去。
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PreModelSwitch",
                "permissionDecision": "allow",
            }
        }, True
    return 0, None, False


def post_output(handler: str) -> tuple[int, dict | None]:
    """模型已经变成 to_model 之后的 Post。挂在 Pre 上的处理器这里什么都不交。"""
    if handler == "post_exit2":
        return 2, None
    if handler == "post_inject_nested":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "PostModelSwitch",
                "additionalContext": CONTEXT,
            }
        }
    if handler == "post_inject_toplevel":
        return 0, {"additionalContext": CONTEXT}
    return 0, None


def settle_request(handler: str) -> tuple[str, str, int, str, int, int]:
    """用户请求切换。返回 switch、notice、injection、model、pre_fired、post_fired。

    Pre 拦住时模型留在 from_model，Post 不跑。
    Post 的 exit 2 记 user_only，模型已经是 to_model。
    """
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if REQUEST_PRE["hook_event_name"] != "PreModelSwitch":
        raise SystemExit("pre fixture drifted")
    if REQUEST_POST["hook_event_name"] != "PostModelSwitch":
        raise SystemExit("post fixture drifted")
    if REQUEST_PRE["to_model"] != TO_MODEL or REQUEST_POST["to_model"] != TO_MODEL:
        raise SystemExit("to_model drifted")

    code, payload, timed_out = pre_output(handler)
    pre_fired = 1
    if pre_blocks(code, payload, timed_out):
        return "blocked", "none", 0, FROM_MODEL, pre_fired, 0

    post_code, post_payload = post_output(handler)
    notice = "user_only" if post_code == 2 else "none"
    injection = nested_context(post_payload, "PostModelSwitch")
    return "applied", notice, injection, TO_MODEL, pre_fired, 1


def settle_resume() -> tuple[str, str, int, str, int, int]:
    """resume 把模型拨回去。Pre 不调用，哪怕 settings 里挂的是 pre_exit2。"""
    if RESUME_POST["hook_event_name"] != "PostModelSwitch":
        raise SystemExit("resume fixture drifted")
    if RESUME_POST["source"] != "resume":
        raise SystemExit("resume source drifted")
    if RESUME_POST["to_model"] != TO_MODEL:
        raise SystemExit("resume to_model drifted")
    if pre_output("pre_exit2")[0] != 2:
        raise SystemExit("pre exit 2 fixture drifted before the resume path")

    post_code, post_payload = post_output("none")
    if post_code != 0 or post_payload is not None:
        raise SystemExit("resume post was not silent")
    return "applied", "none", 0, TO_MODEL, 0, 1


@dataclass(frozen=True)
class Record:
    name: str
    path: str
    switch: str
    notice: str
    injection: int
    model: str
    pre_fired: int
    post_fired: int

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"path={self.path}",
                f"switch={self.switch}",
                f"notice={self.notice}",
                f"injection={self.injection}",
                f"model={self.model}",
                f"pre_fired={self.pre_fired}",
                f"post_fired={self.post_fired}",
            ]
        )


def run_request(name: str) -> Record:
    switch, notice, injection, model, pre_fired, post_fired = settle_request(name)
    return Record(
        name=name,
        path="request",
        switch=switch,
        notice=notice,
        injection=injection,
        model=model,
        pre_fired=pre_fired,
        post_fired=post_fired,
    )


def run_resume() -> Record:
    switch, notice, injection, model, pre_fired, post_fired = settle_resume()
    return Record(
        name="resume_auto",
        path="resume",
        switch=switch,
        notice=notice,
        injection=injection,
        model=model,
        pre_fired=pre_fired,
        post_fired=post_fired,
    )


def printed_records() -> list[Record]:
    rows = [run_request(name) for name in (
        "pre_exit2",
        "pre_deny_json",
        "pre_block_decision",
        "pre_timeout_sim",
        "post_exit2",
        "post_inject_nested",
        "post_inject_toplevel",
        "none",
    )]
    rows.append(run_resume())
    return rows


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    for name in ("pre_exit2", "pre_deny_json", "pre_block_decision", "pre_timeout_sim"):
        expect(
            records[name],
            path="request",
            switch="blocked",
            notice="none",
            injection=0,
            model=FROM_MODEL,
            pre_fired=1,
            post_fired=0,
        )
    expect(
        records["post_exit2"],
        path="request",
        switch="applied",
        notice="user_only",
        injection=0,
        model=TO_MODEL,
        pre_fired=1,
        post_fired=1,
    )
    expect(
        records["post_inject_nested"],
        path="request",
        switch="applied",
        notice="none",
        injection=1,
        model=TO_MODEL,
        pre_fired=1,
        post_fired=1,
    )
    expect(
        records["post_inject_toplevel"],
        path="request",
        switch="applied",
        notice="none",
        injection=0,
        model=TO_MODEL,
        pre_fired=1,
        post_fired=1,
    )
    expect(
        records["none"],
        path="request",
        switch="applied",
        notice="none",
        injection=0,
        model=TO_MODEL,
        pre_fired=1,
        post_fired=1,
    )
    expect(
        records["resume_auto"],
        path="resume",
        switch="applied",
        notice="none",
        injection=0,
        model=TO_MODEL,
        pre_fired=0,
        post_fired=1,
    )

    if records["post_exit2"].switch != "applied" or records["post_exit2"].notice != "user_only":
        raise SystemExit("Post exit 2 blocked the switch or hid the user notice")
    if records["pre_timeout_sim"].switch != "blocked":
        raise SystemExit("Pre timeout let the switch through")
    if records["post_inject_nested"].model != TO_MODEL or records["post_inject_nested"].injection != 1:
        raise SystemExit("nested context fired before the model changed")
    if records["post_inject_toplevel"].injection != 0:
        raise SystemExit("top-level additionalContext was counted")
    if records["resume_auto"].pre_fired != 0 or records["resume_auto"].switch != "applied":
        raise SystemExit("resume auto-switch ran Pre or failed to apply")
    if records["none"].switch != "applied" or records["none"].injection != 0:
        raise SystemExit("silence became a block or an injection")

    deny_code, deny_payload, deny_timeout = pre_output("pre_deny_json")
    if deny_code != 0 or deny_timeout or not isinstance(deny_payload, dict):
        raise SystemExit("deny JSON fixture did not exit 0")
    if "permissionDecision" in deny_payload:
        raise SystemExit("deny JSON fixture put permissionDecision at the top level")
    inner = deny_payload["hookSpecificOutput"]
    if inner.get("hookEventName") != "PreModelSwitch":
        raise SystemExit("deny JSON fixture lost hookEventName")
    if inner.get("permissionDecision") != "deny":
        raise SystemExit("deny JSON fixture lost permissionDecision")
    if "additionalContext" in inner:
        raise SystemExit("Pre deny fixture carried additionalContext")
    if not pre_blocks(deny_code, deny_payload, deny_timeout):
        raise SystemExit("nested deny did not block")

    toplevel_deny = {"permissionDecision": "deny", "permissionDecisionReason": "顶层"}
    if pre_blocks(0, toplevel_deny, False):
        raise SystemExit("top-level permissionDecision was read")

    allow_payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreModelSwitch",
            "permissionDecision": "allow",
        }
    }
    if pre_blocks(2, allow_payload, False) is not True:
        raise SystemExit("exit 2 was overridden by permissionDecision allow")
    if pre_blocks(0, allow_payload, True) is not True:
        raise SystemExit("timeout honored an allow payload")

    block_code, block_payload, block_timeout = pre_output("pre_block_decision")
    if block_code != 0 or block_timeout or not isinstance(block_payload, dict):
        raise SystemExit("block JSON fixture did not exit 0")
    if block_payload.get("decision") != "block":
        raise SystemExit("block JSON fixture lost decision")
    if "hookSpecificOutput" in block_payload:
        raise SystemExit("block JSON fixture hid decision inside hookSpecificOutput")

    timeout_code, timeout_payload, timeout_flag = pre_output("pre_timeout_sim")
    if not timeout_flag:
        raise SystemExit("timeout fixture did not time out")
    if not isinstance(timeout_payload, dict):
        raise SystemExit("timeout fixture lost the discarded allow payload")
    if timeout_payload["hookSpecificOutput"].get("permissionDecision") != "allow":
        raise SystemExit("timeout fixture was not an allow that must be discarded")
    if timeout_code != 0:
        raise SystemExit("timeout fixture used exit 2 instead of a timeout")

    nested_code, nested_payload = post_output("post_inject_nested")
    if nested_code != 0 or not isinstance(nested_payload, dict):
        raise SystemExit("nested post fixture did not exit 0 with JSON")
    if "additionalContext" in nested_payload:
        raise SystemExit("nested post fixture put additionalContext at the top level")
    post_inner = nested_payload["hookSpecificOutput"]
    if post_inner.get("hookEventName") != "PostModelSwitch":
        raise SystemExit("nested post fixture lost hookEventName")
    if post_inner.get("additionalContext") != CONTEXT:
        raise SystemExit("nested context text drifted")
    if nested_context(nested_payload, "PostModelSwitch") != 1:
        raise SystemExit("nested context was dropped")
    if nested_context(nested_payload, "PreModelSwitch") != 0:
        raise SystemExit("Post context was accepted as Pre context")

    top_code, top_payload = post_output("post_inject_toplevel")
    if top_code != 0 or not isinstance(top_payload, dict):
        raise SystemExit("top-level post fixture did not exit 0 with JSON")
    if "additionalContext" not in top_payload:
        raise SystemExit("top-level post fixture lost additionalContext")
    if "hookSpecificOutput" in top_payload:
        raise SystemExit("top-level post fixture was nested")
    if nested_context(top_payload, "PostModelSwitch") != 0:
        raise SystemExit("top-level additionalContext was read")

    if post_output("post_exit2") != (2, None):
        raise SystemExit("post exit 2 fixture drifted")
    if pre_output("post_exit2") != (0, None, False):
        raise SystemExit("post exit 2 also fired on Pre")
    if post_output("pre_exit2") != (0, None):
        raise SystemExit("pre exit 2 also fired on Post")

    try:
        settle_request("matcher_opus")
    except SystemExit as exc:
        if "unknown handler" not in str(exc):
            raise
    else:
        raise SystemExit("unknown handler was accepted")


def main() -> None:
    records = {row.name: row for row in printed_records()}
    check(records)
    for row in printed_records():
        print(records[row.name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
