#!/usr/bin/env python3
"""伪控制环：权限决定放不放行，隔离决定放行之后能碰到哪。

不调用 API，不读密钥，不访问网络，不碰本机文件系统。
路径是夹具字符串。围栏不是 Seatbelt、bubblewrap、容器或虚拟机。
分类器来源只是标签：allow 不会被记成审计通过。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fence:
    """covers 是这道围栏罩住的工具。write_allow 是写入前缀。

    read_policy=wide：罩住的读不做前缀检查。
    这对应沙箱页上的默认：沙箱内命令能读机器上的大部分路径，包括 ~/.ssh。
    运行时那一页写了默认拒网和收紧写入，没有写默认禁止读宿主密钥。
    夹具不用 wide 以外的读策略去编运行时。
    """

    name: str
    covers: frozenset[str]
    write_allow: tuple[str, ...]
    read_policy: str = "wide"


BASH = Fence("bash_sandbox", frozenset({"Bash"}), ("/work/repo",))
RUNTIME = Fence(
    "sandbox_runtime",
    frozenset({"Bash", "Write", "Read", "Edit", "MCP", "Hook", "WebFetch"}),
    ("/work/repo",),
)


def path_allowed(path: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        root = prefix.rstrip("/")
        if path == root or path.startswith(root + "/"):
            return True
    return False


def decide(tool: str, op: str, path: str, permission: str, fence: Fence) -> str:
    """allow 之后才看围栏。工具不在围栏的名单里，就在宿主上。"""
    if permission == "deny":
        return "denied_by_permission"
    if permission == "ask":
        return "prompted"
    if permission != "allow":
        raise SystemExit(f"unknown permission {permission}")
    if op not in ("read", "write"):
        raise SystemExit(f"unknown op {op}")
    if tool not in fence.covers:
        return "host_path"
    if op == "read" and fence.read_policy == "wide":
        return "ran_inside"
    if path_allowed(path, fence.write_allow):
        return "ran_inside"
    return "blocked_by_isolation"


@dataclass(frozen=True)
class Record:
    name: str
    tool: str
    op: str
    path: str
    permission: str
    source: str
    fence: str
    outcome: str
    note: str

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"permission={self.permission}",
                f"source={self.source}",
                f"tool={self.tool}",
                f"fence={self.fence}",
                f"outcome={self.outcome}",
                f"note={self.note}",
            ]
        )


def run(
    name: str,
    tool: str,
    op: str,
    path: str,
    permission: str,
    fence: Fence,
    note: str,
    source: str = "rule",
) -> Record:
    outcome = decide(tool, op, path, permission, fence)
    if source == "classifier" and outcome == "audit_pass":
        raise SystemExit(f"{name} recorded a classifier allow as an audit pass")
    return Record(
        name=name,
        tool=tool,
        op=op,
        path=path,
        permission=permission,
        source=source,
        fence=fence.name,
        outcome=outcome,
        note=note,
    )


def printed_records() -> list[Record]:
    ssh = "/home/me/.ssh/config"
    key = "/home/me/.ssh/id_rsa"
    aws = "/home/me/.aws/credentials"
    src = "/work/repo/src/app.py"
    return [
        run(
            "allow_outside",
            "Bash",
            "write",
            ssh,
            "allow",
            RUNTIME,
            "write_outside_prefix",
        ),
        run(
            "write_on_host",
            "Write",
            "write",
            ssh,
            "allow",
            BASH,
            "file_tool_on_host",
            source="classifier",
        ),
        run(
            "bypass_write",
            "Write",
            "write",
            ssh,
            "allow",
            BASH,
            "skip_prompts_is_not_a_fence",
            source="bypass",
        ),
        run(
            "bash_read_ssh",
            "Bash",
            "read",
            key,
            "allow",
            BASH,
            "default_read_includes_ssh",
        ),
        run(
            "mcp_host",
            "MCP",
            "read",
            aws,
            "allow",
            BASH,
            "mcp_not_in_shell_fence",
            source="classifier",
        ),
        run(
            "write_fenced",
            "Write",
            "write",
            ssh,
            "allow",
            RUNTIME,
            "write_outside_prefix",
            source="classifier",
        ),
        run(
            "deny_first",
            "Write",
            "write",
            src,
            "deny",
            RUNTIME,
            "permission_before_fence",
        ),
        run(
            "in_repo",
            "Bash",
            "write",
            src,
            "allow",
            BASH,
            "inside_write_prefix",
        ),
    ]


def extra_records() -> list[Record]:
    return [
        run(
            "ask_stops",
            "Bash",
            "write",
            "/work/repo/src/app.py",
            "ask",
            BASH,
            "prompt_does_not_reach_fence",
            source="manual",
        ),
        run(
            "hook_host",
            "Hook",
            "write",
            "/work/repo/src/app.py",
            "allow",
            BASH,
            "hook_not_in_shell_fence",
            source="classifier",
        ),
    ]


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(records["allow_outside"], outcome="blocked_by_isolation", fence="sandbox_runtime")
    expect(
        records["write_on_host"],
        outcome="host_path",
        source="classifier",
        tool="Write",
        fence="bash_sandbox",
        note="file_tool_on_host",
    )
    expect(records["bypass_write"], outcome="host_path", source="bypass", tool="Write")
    expect(records["bash_read_ssh"], outcome="ran_inside", note="default_read_includes_ssh")
    expect(records["mcp_host"], outcome="host_path", tool="MCP", fence="bash_sandbox")
    expect(records["write_fenced"], outcome="blocked_by_isolation", tool="Write")
    expect(records["deny_first"], outcome="denied_by_permission", permission="deny")
    expect(records["in_repo"], outcome="ran_inside", note="inside_write_prefix")
    expect(records["ask_stops"], outcome="prompted", permission="ask")
    expect(records["hook_host"], outcome="host_path", tool="Hook")

    if path_allowed("/work/repo-evil/a.py", ("/work/repo",)):
        raise SystemExit("prefix matched a sibling path")
    if not path_allowed("/work/repo", ("/work/repo",)):
        raise SystemExit("exact project root was outside the prefix")

    for record in records.values():
        if record.outcome == "audit_pass":
            raise SystemExit(f"{record.name} counted an allow as an audit pass")
        if record.source == "classifier" and "audit" in record.outcome:
            raise SystemExit(f"{record.name} folded the classifier into the outcome")

    printed = {records[name].outcome for name in (
        "allow_outside",
        "write_on_host",
        "bypass_write",
        "bash_read_ssh",
        "mcp_host",
        "write_fenced",
        "deny_first",
        "in_repo",
    )}
    if printed != {
        "blocked_by_isolation",
        "host_path",
        "ran_inside",
        "denied_by_permission",
    }:
        raise SystemExit(f"outcomes {printed}")


def main() -> None:
    records = {row.name: row for row in [*printed_records(), *extra_records()]}
    check(records)
    for row in printed_records():
        print(records[row.name].line())
    print("result=pass")


if __name__ == "__main__":
    main()
