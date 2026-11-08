#!/usr/bin/env python3
"""伪控制环：SessionStart 的 exit 2 拦不住提示，UserPromptSubmit 可以。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
先走一次 SessionStart，再走一次带 prompt 字段的 UserPromptSubmit。
处理器是夹具，不是 settings.json 里的 hook。
exit 2 的差别来自 Hooks reference 的退出码表。
additionalContext 必须在 hookSpecificOutput 里，来自 hooks-guide 的嵌套例子。
顶层同名字段不计注入。原文 prompt 不会被换成注入的那一句。
"""

from __future__ import annotations

from dataclasses import dataclass

HANDLERS = frozenset(
    {
        "none",
        "session_start_exit2",
        "user_prompt_exit2",
        "user_prompt_block_json",
        "inject_nested",
        "inject_toplevel",
    }
)
ORIGINAL = "列出当前分支，别把生产密钥贴进对话"
CONTEXT = "Current branch: release-42. Deploy freeze until Friday."
USER_PROMPT_INPUT = {
    "hook_event_name": "UserPromptSubmit",
    "prompt": ORIGINAL,
}
SESSION_START_INPUT = {
    "hook_event_name": "SessionStart",
    "source": "startup",
}


def nested_context(payload: dict | None) -> int:
    """只认 hookSpecificOutput 里的 additionalContext。顶层同名字段不算。"""
    if not isinstance(payload, dict):
        return 0
    nested = payload.get("hookSpecificOutput")
    if not isinstance(nested, dict):
        return 0
    if nested.get("hookEventName") != "UserPromptSubmit":
        return 0
    text = nested.get("additionalContext")
    if isinstance(text, str) and text:
        return 1
    return 0


def session_start_output(handler: str) -> tuple[int, dict | None]:
    """SessionStart 这一刀。只有 session_start_exit2 以 2 退出。"""
    if handler == "session_start_exit2":
        return 2, None
    return 0, None


def user_prompt_output(handler: str) -> tuple[int, dict | None]:
    """UserPromptSubmit 这一刀。挂错事件时这里什么都不交。"""
    if handler == "user_prompt_exit2":
        return 2, None
    if handler == "user_prompt_block_json":
        return 0, {
            "decision": "block",
            "reason": "生产密钥不能进模型",
        }
    if handler == "inject_nested":
        return 0, {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": CONTEXT,
            }
        }
    if handler == "inject_toplevel":
        return 0, {"additionalContext": CONTEXT}
    return 0, None


def settle(handler: str) -> tuple[str, str, int, str]:
    """返回 prompt 命运、exit 2 通知、注入次数、原话是否还在。

    SessionStart 的 exit 2 只记 user_only，提示仍 reaches_model。
    UserPromptSubmit 的 exit 2 和顶层 decision block 记 blocked。
    嵌套的 additionalContext 记 injection=1，不改 prompt。
    顶层同名字段记 injection=0。沉默不是拦截。
    """
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if SESSION_START_INPUT["hook_event_name"] != "SessionStart":
        raise SystemExit("session fixture drifted")
    if USER_PROMPT_INPUT["hook_event_name"] != "UserPromptSubmit":
        raise SystemExit("prompt fixture drifted")

    prompt = USER_PROMPT_INPUT["prompt"]
    if prompt != ORIGINAL:
        raise SystemExit("prompt was replaced before the hook")

    notice = "none"
    code, _payload = session_start_output(handler)
    if code == 2:
        # 参考页：SessionStart 的 exit 2 不拦，stderr 只给用户看。
        notice = "user_only"

    fate = "reaches_model"
    ups_code, ups_payload = user_prompt_output(handler)
    injection = nested_context(ups_payload)
    blocked = ups_code == 2 or (
        isinstance(ups_payload, dict) and ups_payload.get("decision") == "block"
    )
    if blocked:
        fate = "blocked"

    if prompt != ORIGINAL or CONTEXT in prompt:
        text = "replaced"
    else:
        text = "unchanged"
    return fate, notice, injection, text


@dataclass(frozen=True)
class Record:
    name: str
    prompt: str
    notice: str
    injection: int
    prompt_text: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"prompt={self.prompt}",
                f"notice={self.notice}",
                f"injection={self.injection}",
                f"prompt_text={self.prompt_text}",
            ]
        )


def run(name: str) -> Record:
    fate, notice, injection, text = settle(name)
    return Record(
        name=name,
        prompt=fate,
        notice=notice,
        injection=injection,
        prompt_text=text,
    )


def printed_records() -> list[Record]:
    return [run(name) for name in (
        "session_start_exit2",
        "user_prompt_exit2",
        "user_prompt_block_json",
        "inject_nested",
        "inject_toplevel",
        "none",
    )]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["session_start_exit2"],
        prompt="reaches_model",
        notice="user_only",
        injection=0,
        prompt_text="unchanged",
    )
    expect(
        records["user_prompt_exit2"],
        prompt="blocked",
        notice="none",
        injection=0,
        prompt_text="unchanged",
    )
    expect(
        records["user_prompt_block_json"],
        prompt="blocked",
        notice="none",
        injection=0,
        prompt_text="unchanged",
    )
    expect(
        records["inject_nested"],
        prompt="reaches_model",
        notice="none",
        injection=1,
        prompt_text="unchanged",
    )
    expect(
        records["inject_toplevel"],
        prompt="reaches_model",
        notice="none",
        injection=0,
        prompt_text="unchanged",
    )
    expect(
        records["none"],
        prompt="reaches_model",
        notice="none",
        injection=0,
        prompt_text="unchanged",
    )

    if records["session_start_exit2"].prompt == "blocked":
        raise SystemExit("SessionStart exit 2 blocked the prompt")
    if records["none"].prompt == "blocked" or records["none"].injection != 0:
        raise SystemExit("silence became a block or an injection")
    if records["inject_nested"].injection != 1:
        raise SystemExit("nested additionalContext was not counted")
    if records["inject_nested"].prompt_text != "unchanged":
        raise SystemExit("nested context replaced the prompt")
    if records["inject_toplevel"].injection != 0:
        raise SystemExit("top-level additionalContext was counted")
    if records["inject_toplevel"].prompt != "reaches_model":
        raise SystemExit("an ignored field blocked the prompt")
    if records["user_prompt_exit2"].prompt != "blocked":
        raise SystemExit("UserPromptSubmit exit 2 did not block")
    if records["user_prompt_block_json"].prompt != "blocked":
        raise SystemExit("decision block did not block")

    toplevel_code, toplevel_payload = user_prompt_output("inject_toplevel")
    if toplevel_code != 0 or not isinstance(toplevel_payload, dict):
        raise SystemExit("top-level fixture did not exit 0 with JSON")
    if "additionalContext" not in toplevel_payload:
        raise SystemExit("top-level fixture lost additionalContext")
    if "hookSpecificOutput" in toplevel_payload:
        raise SystemExit("top-level fixture was nested")
    if nested_context(toplevel_payload) != 0:
        raise SystemExit("top-level additionalContext was read")

    nested_code, nested_payload = user_prompt_output("inject_nested")
    if nested_code != 0 or not isinstance(nested_payload, dict):
        raise SystemExit("nested fixture did not exit 0 with JSON")
    if "additionalContext" in nested_payload:
        raise SystemExit("nested fixture put additionalContext at the top level")
    inner = nested_payload["hookSpecificOutput"]
    if inner.get("additionalContext") != CONTEXT:
        raise SystemExit("nested context text drifted")
    if inner["additionalContext"] == USER_PROMPT_INPUT["prompt"]:
        raise SystemExit("context and prompt were the same string")
    if nested_context(nested_payload) != 1:
        raise SystemExit("nested context was dropped")

    block_code, block_payload = user_prompt_output("user_prompt_block_json")
    if block_code != 0 or not isinstance(block_payload, dict):
        raise SystemExit("block JSON fixture did not exit 0")
    if block_payload.get("decision") != "block":
        raise SystemExit("block JSON fixture lost decision")
    if "hookSpecificOutput" in block_payload:
        raise SystemExit("block JSON fixture hid decision inside hookSpecificOutput")

    if session_start_output("session_start_exit2") != (2, None):
        raise SystemExit("session exit 2 fixture drifted")
    if user_prompt_output("session_start_exit2") != (0, None):
        raise SystemExit("session exit 2 also fired on UserPromptSubmit")

    try:
        settle("matcher_startup")
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
