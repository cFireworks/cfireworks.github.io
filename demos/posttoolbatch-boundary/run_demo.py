#!/usr/bin/env python3
"""伪控制环：PostToolBatch 在整批之后只走一次，拦的是下一轮。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
一批三只 Read 的 tool_response 是带行号的字符串，按 Hooks reference 的
PostToolBatch 例子，不是 PostToolUse 里 Bash 的 stdout 对象。
处理器是夹具，不是 settings.json 里的 hook。
"""

from __future__ import annotations

from dataclasses import dataclass

HANDLERS = frozenset(
    {
        "none",
        "annotate_batch",
        "block_batch",
        "misparse_as_object",
        "per_tool_annotate",
        "exit2",
    }
)
NOTE = "本批调用都已落地。不要按刀再注一遍。"
# 参考页的 Read 例子是带行号的文本。夹具用短字符串，不声称这是某个仓库里的文件。
BATCH = (
    {
        "tool_name": "Read",
        "tool_use_id": "toolu_01",
        "tool_response": "1\tfrom __future__ import annotations\n",
    },
    {
        "tool_name": "Read",
        "tool_use_id": "toolu_02",
        "tool_response": "1\tclass Ledger:\n",
    },
    {
        "tool_name": "Read",
        "tool_use_id": "toolu_03",
        "tool_response": "1\tdef post(self):\n",
    },
)
# 对照：PostToolUse 的 Bash 替换例子是对象。批边界的夹具输入不是这个形状。
STRUCTURED_STDOUT = {
    "stdout": "ok\n",
    "stderr": "",
    "interrupted": False,
    "isImage": False,
}


def stdout_of(tool_response: object) -> str:
    """单刀脚本会这么读。字符串在 ["stdout"] 上抛 TypeError。"""
    value = tool_response["stdout"]  # type: ignore[index]
    if not isinstance(value, str):
        raise TypeError("stdout is not a string")
    return value


def settle(handler: str) -> tuple[int, int, int, str, str, str]:
    """返回单刀次数、批次数、注入次数、loop、parse、failure。

    三只都成功，所以 PostToolUse 计 3，PostToolBatch 计 1。
    批注只在 annotate_batch 上记 1。每刀各注一句记 3，那不是批边界。
    block 和 exit 2 停的是下一轮，不改 already_ran。
    误解析记成非阻断，循环继续。没写 onFailure 的那条，夹具不编 block。
    """
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")

    post_tool_use = len(BATCH)
    post_tool_batch = 1
    if post_tool_use != 3 or post_tool_batch != 1:
        raise SystemExit("batch cardinality drifted")

    parse = "ok"
    failure = "none"
    injection = 0
    loop = "continues"

    if handler == "annotate_batch":
        injection = 1
    elif handler == "per_tool_annotate":
        injection = post_tool_use
    elif handler in {"block_batch", "exit2"}:
        loop = "stop_before_next_model"
    elif handler == "misparse_as_object":
        parse = "error"
        failure = "non_blocking"
        for call in BATCH:
            try:
                stdout_of(call["tool_response"])
            except TypeError:
                continue
            raise SystemExit("string tool_response exposed stdout")
    elif handler == "none":
        pass

    return post_tool_use, post_tool_batch, injection, loop, parse, failure


@dataclass(frozen=True)
class Record:
    name: str
    post_tool_use: int
    post_tool_batch: int
    injection_count: int
    loop: str
    side_effect: str
    parse: str
    failure: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"post_tool_use={self.post_tool_use}",
                f"post_tool_batch={self.post_tool_batch}",
                f"injection_count={self.injection_count}",
                f"loop={self.loop}",
                f"side_effect={self.side_effect}",
                f"parse={self.parse}",
                f"failure={self.failure}",
            ]
        )


def run(name: str, handler: str) -> Record:
    post_tool_use, post_tool_batch, injection, loop, parse, failure = settle(handler)
    return Record(
        name=name,
        post_tool_use=post_tool_use,
        post_tool_batch=post_tool_batch,
        injection_count=injection,
        loop=loop,
        side_effect="already_ran",
        parse=parse,
        failure=failure,
    )


def printed_records() -> list[Record]:
    return [
        run("annotate_batch", "annotate_batch"),
        run("block_batch", "block_batch"),
        run("misparse_as_object", "misparse_as_object"),
        run("none", "none"),
    ]


def extra_records() -> list[Record]:
    return [
        run("per_tool_annotate", "per_tool_annotate"),
        run("exit2", "exit2"),
    ]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    ids = [call["tool_use_id"] for call in BATCH]
    if len(ids) != len(set(ids)):
        raise SystemExit("tool_use_id collided")
    for call in BATCH:
        if call["tool_name"] != "Read":
            raise SystemExit("fixture drifted off the documented Read example")
        if not isinstance(call["tool_response"], str):
            raise SystemExit("batch tool_response was not a string")
        if not str(call["tool_response"]).startswith("1\t"):
            raise SystemExit("Read tool_response lost the line-number prefix")

    if stdout_of(STRUCTURED_STDOUT) != "ok\n":
        raise SystemExit("structured stdout control did not read")
    try:
        stdout_of(BATCH[0]["tool_response"])
    except TypeError:
        pass
    else:
        raise SystemExit("string tool_response was accepted as stdout")

    expect(
        records["annotate_batch"],
        post_tool_use=3,
        post_tool_batch=1,
        injection_count=1,
        loop="continues",
        side_effect="already_ran",
        parse="ok",
        failure="none",
    )
    expect(
        records["block_batch"],
        post_tool_use=3,
        post_tool_batch=1,
        injection_count=0,
        loop="stop_before_next_model",
        side_effect="already_ran",
        parse="ok",
        failure="none",
    )
    expect(
        records["misparse_as_object"],
        post_tool_use=3,
        post_tool_batch=1,
        injection_count=0,
        loop="continues",
        side_effect="already_ran",
        parse="error",
        failure="non_blocking",
    )
    expect(
        records["none"],
        post_tool_use=3,
        post_tool_batch=1,
        injection_count=0,
        loop="continues",
        side_effect="already_ran",
        parse="ok",
        failure="none",
    )
    expect(
        records["per_tool_annotate"],
        post_tool_use=3,
        post_tool_batch=1,
        injection_count=3,
        loop="continues",
        side_effect="already_ran",
    )
    expect(
        records["exit2"],
        post_tool_use=3,
        post_tool_batch=1,
        injection_count=0,
        loop="stop_before_next_model",
        side_effect="already_ran",
        failure="none",
    )

    if records["annotate_batch"].injection_count != 1:
        raise SystemExit("batch note was not injected once")
    if records["per_tool_annotate"].injection_count != 3:
        raise SystemExit("per-tool notes did not follow the tool count")
    if records["block_batch"].side_effect != "already_ran":
        raise SystemExit("decision block was counted as a rollback")
    if records["exit2"].loop != "stop_before_next_model":
        raise SystemExit("exit 2 did not stop before the next model call")
    if records["misparse_as_object"].failure != "non_blocking":
        raise SystemExit("a bad stdout read blocked the loop")
    if records["misparse_as_object"].loop != "continues":
        raise SystemExit("a non-blocking parse error stopped the loop")
    if records["none"].loop != "continues" or records["none"].injection_count != 0:
        raise SystemExit("silence became a note or a stop")

    for record in records.values():
        if record.post_tool_use != 3 or record.post_tool_batch != 1:
            raise SystemExit(f"{record.name} broke the 3-to-1 count")
        if record.side_effect != "already_ran":
            raise SystemExit(f"{record.name} undid a tool that already ran")
        if record.injection_count > record.post_tool_use:
            raise SystemExit(f"{record.name} injected more notes than tools")

    try:
        settle("matcher_bash")
    except SystemExit as exc:
        if "unknown handler" not in str(exc):
            raise
    else:
        raise SystemExit("unknown handler was accepted")


def main() -> None:
    records = {row.name: row for row in [*printed_records(), *extra_records()]}
    check(records)
    for row in printed_records():
        print(records[row.name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
