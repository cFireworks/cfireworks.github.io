#!/usr/bin/env python3
"""伪控制环：PostToolUse 的 updatedToolOutput 只改模型看见的那一份。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
事件已经是工具成功之后。处理器是夹具，不是 settings.json 里的 hook。
模型视图、形状回退和遥测只转述 Hooks reference 的 PostToolUse 决策控制。
字符串 AKIA_EXAMPLE_NOT_REAL 与 sk-example-not-a-real-key 是假凭证。
"""

from __future__ import annotations

from dataclasses import dataclass

KINDS = frozenset({"builtin", "mcp"})
HANDLERS = frozenset(
    {
        "none",
        "replace",
        "annotate",
        "block_only",
        "bad_shape",
        "replace_and_note",
        "block_and_replace",
    }
)
SECRETS = ("AKIA_EXAMPLE_NOT_REAL", "sk-example-not-a-real-key")
RAW_STDOUT = (
    "AWS_ACCESS_KEY_ID=AKIA_EXAMPLE_NOT_REAL\n"
    "OPENAI_API_KEY=sk-example-not-a-real-key\n"
)
REDACTED_STDOUT = "AWS_ACCESS_KEY_ID=[redacted]\nOPENAI_API_KEY=[redacted]\n"
NOTE = "这段输出可能含凭证。不要写进回复。"
REASON = "不要根据这段输出继续调用。"

# 参考页的 Bash 例子是对象，不是一段字符串。夹具只把「纯字符串」当成对不上的形状。
# 缺字段、多字段会不会被真实校验丢掉，参考页没有逐项写，这里不编。
REDACTED_BASH = {
    "stdout": REDACTED_STDOUT,
    "stderr": "",
    "interrupted": False,
    "isImage": False,
}
BAD_SHAPE = "[redacted]"


def has_secret(text: str) -> bool:
    return any(secret in text for secret in SECRETS)


def secret_state(text: str) -> str:
    hits = [secret in text for secret in SECRETS]
    if hits == [True, True]:
        return "yes"
    if hits == [False, False]:
        return "no"
    raise SystemExit(f"partial secret leak in {text!r}")


def bash_shape_ok(value: object) -> bool:
    """参考页对照的是结构化对象和纯字符串。不是对象的值算对不上。

    夹具里用到的坏形状是纯字符串。缺字段、多字段、字段类型不对会不会被真实模式丢掉，
    参考页没有逐项写，夹具不编。通过的例子仍是带 stdout、stderr、interrupted、isImage 的对象。
    """
    return isinstance(value, dict)


def replacement_for(handler: str) -> object | None:
    if handler in {"replace", "replace_and_note", "block_and_replace"}:
        return REDACTED_BASH
    if handler == "bad_shape":
        return BAD_SHAPE
    if handler in {"annotate", "block_only", "none"}:
        return None
    raise SystemExit(f"unknown handler {handler}")


def settle(kind: str, handler: str) -> tuple[str, str, str, str, str]:
    """返回 shape、模型看见的文本、note、reason、telemetry 文本。

    工具已经跑完。遥测始终是原始 stdout。
    内置工具形状不对时忽略替换。MCP 不做这层校验，交什么模型就看见什么。
    additionalContext 和 decision block 都不拿掉原始输出，除非同时给了通过的替换。
    """
    if kind not in KINDS:
        raise SystemExit(f"unknown kind {kind}")
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")

    replacement = replacement_for(handler)
    note = NOTE if handler in {"annotate", "replace_and_note"} else ""
    reason = REASON if handler in {"block_only", "block_and_replace"} else ""

    if replacement is None:
        shape = "not_offered"
        model_stdout = RAW_STDOUT
    elif kind == "mcp":
        shape = "skipped"
        model_stdout = replacement if isinstance(replacement, str) else replacement["stdout"]
    elif bash_shape_ok(replacement):
        shape = "accepted"
        model_stdout = replacement["stdout"]
    else:
        shape = "rejected"
        model_stdout = RAW_STDOUT

    visible = model_stdout + note + reason
    return shape, visible, "present" if note else "none", "present" if reason else "none", RAW_STDOUT


@dataclass(frozen=True)
class Record:
    name: str
    kind: str
    handler: str
    side_effect: str
    shape: str
    model_has_secret: str
    note: str
    reason: str
    telemetry_has_secret: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"kind={self.kind}",
                f"handler={self.handler}",
                f"side_effect={self.side_effect}",
                f"shape={self.shape}",
                f"model_has_secret={self.model_has_secret}",
                f"note={self.note}",
                f"reason={self.reason}",
                f"telemetry_has_secret={self.telemetry_has_secret}",
            ]
        )


def run(name: str, kind: str, handler: str) -> Record:
    shape, visible, note, reason, telemetry = settle(kind, handler)
    return Record(
        name=name,
        kind=kind,
        handler=handler,
        side_effect="already_ran",
        shape=shape,
        model_has_secret=secret_state(visible),
        note=note,
        reason=reason,
        telemetry_has_secret=secret_state(telemetry),
    )


def printed_records() -> list[Record]:
    return [
        run("replace", "builtin", "replace"),
        run("annotate", "builtin", "annotate"),
        run("block_only", "builtin", "block_only"),
        run("bad_shape", "builtin", "bad_shape"),
        run("none", "builtin", "none"),
    ]


def extra_records() -> list[Record]:
    return [
        run("replace_and_note", "builtin", "replace_and_note"),
        run("block_and_replace", "builtin", "block_and_replace"),
        run("mcp_bad_shape", "mcp", "bad_shape"),
        run("mcp_replace", "mcp", "replace"),
    ]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["replace"],
        kind="builtin",
        handler="replace",
        side_effect="already_ran",
        shape="accepted",
        model_has_secret="no",
        note="none",
        reason="none",
        telemetry_has_secret="yes",
    )
    expect(
        records["annotate"],
        shape="not_offered",
        model_has_secret="yes",
        note="present",
        reason="none",
        telemetry_has_secret="yes",
    )
    expect(
        records["block_only"],
        shape="not_offered",
        model_has_secret="yes",
        note="none",
        reason="present",
        side_effect="already_ran",
    )
    expect(
        records["bad_shape"],
        kind="builtin",
        shape="rejected",
        model_has_secret="yes",
        note="none",
        reason="none",
    )
    expect(
        records["none"],
        shape="not_offered",
        model_has_secret="yes",
        note="none",
        reason="none",
    )

    expect(
        records["replace_and_note"],
        shape="accepted",
        model_has_secret="no",
        note="present",
        reason="none",
        telemetry_has_secret="yes",
    )
    expect(
        records["block_and_replace"],
        shape="accepted",
        model_has_secret="no",
        note="none",
        reason="present",
        telemetry_has_secret="yes",
    )
    expect(
        records["mcp_bad_shape"],
        kind="mcp",
        handler="bad_shape",
        shape="skipped",
        model_has_secret="no",
        telemetry_has_secret="yes",
    )
    expect(
        records["mcp_replace"],
        kind="mcp",
        shape="skipped",
        model_has_secret="no",
        telemetry_has_secret="yes",
    )

    if records["replace"].model_has_secret == "yes":
        raise SystemExit("replacement left the secret in the model view")
    if records["annotate"].model_has_secret == "no":
        raise SystemExit("additionalContext removed the tool result")
    if records["block_only"].model_has_secret == "no":
        raise SystemExit("decision block removed the original output")
    if records["block_only"].side_effect != "already_ran":
        raise SystemExit("decision block was counted as a rollback")
    if records["bad_shape"].model_has_secret == "no":
        raise SystemExit("a bad builtin shape replaced the original output")
    if records["mcp_bad_shape"].shape == "rejected":
        raise SystemExit("MCP applied the builtin shape check")
    if records["none"].model_has_secret == "no":
        raise SystemExit("silence redacted the output")

    for record in records.values():
        if record.side_effect != "already_ran":
            raise SystemExit(f"{record.name} undid a tool that already ran")
        if record.telemetry_has_secret != "yes":
            raise SystemExit(f"{record.name} dropped the original from telemetry")
        if record.shape in {"rejected", "not_offered"} and record.model_has_secret != "yes":
            raise SystemExit(f"{record.name} hid the original without a replacement")
        if record.shape == "accepted" and record.model_has_secret != "no":
            raise SystemExit(f"{record.name} accepted a replacement that still leaks")

    try:
        settle("builtin", "exit2")
    except SystemExit as exc:
        if "unknown handler" not in str(exc):
            raise
    else:
        raise SystemExit("unknown handler was accepted")

    printed = {records[name].model_has_secret for name in (
        "replace",
        "annotate",
        "block_only",
        "bad_shape",
        "none",
    )}
    if printed != {"yes", "no"}:
        raise SystemExit(f"model views {printed}")


def main() -> None:
    records = {row.name: row for row in [*printed_records(), *extra_records()]}
    check(records)
    for row in printed_records():
        print(records[row.name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
