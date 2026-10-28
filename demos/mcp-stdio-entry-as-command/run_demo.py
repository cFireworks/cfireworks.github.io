#!/usr/bin/env python3
"""Inventory stdio MCP entries and show how --resume is bound.

The fixtures are hand-written and safe. This script prints the command and
args a host would launch. It does not spawn processes, import vendor SDKs,
or open network connections. Run it twice: stdout must match, and the last
line is "checks passed".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
# Release note for claude-agent-sdk 0.2.124 names these on Windows.
# Applied on every platform so the transcript does not depend on the OS.
CMD_METACHAR = set("&|<>^%!\"")
REMOTE_TYPES = {"http", "sse", "ws", "streamable-http"}


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def classify(entry: dict) -> tuple[str, bool]:
    """Return (kind, launch). launch is true only for a stdio command entry."""
    command = entry.get("command")
    url = entry.get("url")
    transport = entry.get("type")
    if command and url:
        return "review-both", False
    if isinstance(command, str) and command:
        args = entry.get("args", [])
        if args is None:
            args = []
        if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
            return "review-args", False
        return "stdio", True
    if isinstance(url, str) and url and not transport:
        return "url-without-type", False
    if isinstance(url, str) and url and transport in REMOTE_TYPES:
        return "remote", False
    return "review-unknown", False


def format_entry(source: str, name: str, entry: dict) -> str:
    kind, launch = classify(entry)
    launch_text = "yes" if launch else "no"
    parts = [
        f"source={source}",
        f"name={name}",
        f"kind={kind}",
        f"launch={launch_text}",
    ]
    if kind == "stdio":
        parts.append(f"command={entry['command']}")
        parts.append(f"args={dumps(entry.get('args') or [])}")
    elif kind == "remote":
        parts.append(f"type={entry['type']}")
        parts.append(f"url={entry['url']}")
    elif kind == "url-without-type":
        parts.append(f"url={entry['url']}")
    return " ".join(parts)


def load_servers(path: Path) -> list[tuple[str, dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "mcpServers" in payload:
        servers = payload["mcpServers"]
    else:
        servers = payload["mcp"]["servers"]
    require(isinstance(servers, dict), f"{path.name} servers")
    return sorted(servers.items(), key=lambda item: item[0])


def bind_resume(value: str, style: str) -> list[str]:
    """Show the argv shape. Nothing is executed."""
    if style == "split":
        return ["--resume", value]
    if style == "equals":
        return [f"--resume={value}"]
    raise ValueError(style)


def format_argv(style: str, value: str) -> str:
    tokens = bind_resume(value, style)
    detached = style == "split" and value.startswith("-")
    return (
        f"argv style={style} value={dumps(value)} "
        f"tokens={dumps(tokens)} count={len(tokens)} "
        f"detached={'yes' if detached else 'no'}"
    )


def session_decision(value: str) -> tuple[bool, str]:
    """App-side checks. Binding and shape are separate."""
    if value == "":
        return False, "empty"
    if value.startswith("-"):
        return False, "dash-leading"
    if any(ch in CMD_METACHAR or ch in "\r\n" for ch in value):
        return False, "cmd-metachar"
    if UUID_RE.fullmatch(value):
        return True, "uuid"
    return False, "not-uuid"


def format_session(value: str) -> str:
    accept, reason = session_decision(value)
    if accept:
        return f"session value={dumps(value)} accept=yes reason={reason}"
    return f"session value={dumps(value)} accept=no reason={reason}"


def main() -> None:
    here = Path(__file__).resolve().parent
    lines: list[str] = []
    for name in ("claude.mcp.json", "zcode.config.json"):
        for server_name, entry in load_servers(here / "fixtures" / name):
            lines.append(format_entry(name, server_name, entry))

    resume_uuid = "11111111-1111-4111-8111-111111111111"
    lines.append(format_argv("split", "--version"))
    lines.append(format_argv("equals", "--version"))
    lines.append(format_argv("equals", resume_uuid))
    for value in (resume_uuid, "--version", "", "not-a-uuid", "abc&def"):
        lines.append(format_session(value))

    by_name = {line.split(" ", 2)[1]: line for line in lines if line.startswith("source=")}
    require("name=notes" in by_name, "notes present")
    require("kind=stdio launch=yes command=python3" in by_name["name=notes"], "notes stdio")
    require('args=["-m","demo_notes"]' in by_name["name=notes"], "notes args")
    require("name=shared" in by_name and "kind=remote launch=no" in by_name["name=shared"], "shared remote")
    require("name=typo" in by_name and "kind=url-without-type launch=no" in by_name["name=typo"], "typo")
    require("name=memory" in by_name and "command=python3" in by_name["name=memory"], "memory")
    require('args=["-m","demo_memory"]' in by_name["name=memory"], "memory args")

    split = bind_resume("--version", "split")
    equals = bind_resume("--version", "equals")
    require(split == ["--resume", "--version"], "split tokens")
    require(equals == ["--resume=--version"] and len(equals) == 1, "equals token")
    require(split[1].startswith("-") and not equals[0].startswith("--resume --"), "detach shape")

    require(session_decision(resume_uuid) == (True, "uuid"), "uuid accepted")
    require(session_decision("--version") == (False, "dash-leading"), "dash rejected")
    require(session_decision("") == (False, "empty"), "empty rejected")
    require(session_decision("not-a-uuid") == (False, "not-uuid"), "shape rejected")
    require(session_decision("abc&def") == (False, "cmd-metachar"), "meta rejected")
    require(session_decision(resume_uuid)[0] and "&" not in resume_uuid, "uuid has no meta")

    text = "\n".join(lines) + "\nchecks passed\n"
    require(text.endswith("checks passed\n"), "trailer")
    print(text, end="")


if __name__ == "__main__":
    main()
