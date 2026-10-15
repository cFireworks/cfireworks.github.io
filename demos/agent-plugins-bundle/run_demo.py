#!/usr/bin/env python3
"""Build a minimal Agent Plugins 1.0.0 directory and check a few rules.

The rules come from the published 1.0.0 specification:

- plugin.json requires the canonical $schema and a name of 1-64 characters
  using a-z, 0-9, hyphens, and periods, with no "--" or ".."
- mcp.json $schema must name the same Agent Plugins version as plugin.json
- a stdio command is one token: a bare name, or a plugin-relative path
  that starts with "./" and stays inside the plugin root
- cwd, when set, must be a plugin-relative path starting with "./"
  (this script does not expand ${PLUGIN_ROOT} or ${PLUGIN_DATA})

A version mismatch disables MCP for that package and leaves skills in place.
The script does not start a subprocess, speak MCP, or load the directory in
Cursor, VS Code, or any other client. bin/echo-server is only a file on disk.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path("/tmp/agent-plugins-bundle/greet-tools")
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
VERSION_RE = re.compile(r"/schemas/(\d+\.\d+\.\d+)/")

SKILL_MD = """---
name: greet
description: Greet the user and offer help.
---

Greet the user and offer help.
"""

ECHO_SERVER = """#!/bin/sh
# Not executed by this demo. A client would launch it as one stdio token.
printf '%s\\n' 'echo-server'
"""


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"check failed: {message}")


def schema_version(url: str) -> str | None:
    match = VERSION_RE.search(url)
    return match.group(1) if match else None


def name_problem(name: str) -> str | None:
    if not 1 <= len(name) <= 64:
        return "length"
    if not re.fullmatch(r"[a-z0-9.\-]+", name):
        return "charset"
    if not (name[0].isalnum() and name[-1].isalnum()):
        return "edge"
    if "--" in name:
        return "consecutive-hyphens"
    if ".." in name:
        return "consecutive-periods"
    return None


def escapes_root(root: Path, raw: str) -> bool:
    resolved = (root / raw).resolve()
    root_resolved = root.resolve()
    return resolved != root_resolved and root_resolved not in resolved.parents


def command_problem(root: Path, command: str) -> str | None:
    if "/" not in command and "\\" not in command:
        return None
    if escapes_root(root, command):
        return "escapes-root"
    if not command.startswith("./"):
        return "not-plugin-relative"
    return None


def cwd_problem(root: Path, cwd: str) -> str | None:
    if not cwd.startswith("./"):
        return "not-plugin-relative"
    if escapes_root(root, cwd):
        return "escapes-root"
    return None


def build(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    (root / "skills" / "greet").mkdir(parents=True)
    (root / "bin").mkdir()
    (root / "data").mkdir()
    (root / "plugin.json").write_text(
        json.dumps(
            {"$schema": PLUGIN_SCHEMA, "name": "greet-tools"},
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "skills" / "greet" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    (root / "mcp.json").write_text(
        json.dumps(
            {
                "$schema": MCP_SCHEMA,
                "mcpServers": {
                    "echo": {
                        "type": "stdio",
                        "command": "./bin/echo-server",
                        "cwd": "./data",
                    }
                },
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    script = root / "bin" / "echo-server"
    script.write_text(ECHO_SERVER, encoding="utf-8")
    script.chmod(0o755)


def frontmatter_name(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    for line in text[4:end].splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    return None


def main() -> None:
    build(ROOT)
    plugin = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    mcp = json.loads((ROOT / "mcp.json").read_text(encoding="utf-8"))
    skill_text = (ROOT / "skills" / "greet" / "SKILL.md").read_text(encoding="utf-8")
    skill_name = frontmatter_name(skill_text)
    server = mcp["mcpServers"]["echo"]

    print(f"python {sys.version.split()[0]}")
    print(
        "built greet-tools files=plugin.json,skills/greet/SKILL.md,"
        "mcp.json,bin/echo-server,data/"
    )
    print(f"manifest schema={plugin['$schema']} name={plugin['name']}")
    print(f"skill skills/greet/SKILL.md frontmatter_name={skill_name}")
    print(
        f"mcp echo type={server['type']} command={server['command']} "
        f"cwd={server['cwd']}"
    )

    require(plugin["$schema"] == PLUGIN_SCHEMA, "plugin schema")
    require(name_problem(plugin["name"]) is None, "plugin name")
    require(skill_name == "greet", "skill name")
    require(server["command"] == "./bin/echo-server", "bundled command")
    require((ROOT / "bin" / "echo-server").is_file(), "echo-server exists")

    samples = [
        ("greet-tools", None),
        ("acme.tools", None),
        ("My-Plugin", "charset"),
        ("-start", "edge"),
        ("has--double", "consecutive-hyphens"),
        ("too.many..dots", "consecutive-periods"),
        ("", "length"),
    ]
    for name, expected in samples:
        got = name_problem(name)
        label = "<empty>" if name == "" else name
        if got is None:
            print(f"name accept {label}")
        else:
            print(f"name reject {label} reason={got}")
        require(got == expected, f"name {label}")

    plugin_version = schema_version(plugin["$schema"])
    mcp_version = schema_version(mcp["$schema"])
    require(plugin_version == mcp_version == "1.0.0", "schema versions")
    print(f"schema match plugin={plugin_version} mcp={mcp_version}")

    mismatched = "https://agent-plugins.org/schemas/1.0.1/mcp.schema.json"
    mismatch_version = schema_version(mismatched)
    mcp_enabled = mismatch_version == plugin_version
    skills_kept = (ROOT / "skills" / "greet" / "SKILL.md").is_file()
    print(
        f"schema mismatch plugin={plugin_version} mcp={mismatch_version} "
        f"mcp={'enabled' if mcp_enabled else 'disabled'} "
        f"skills={'kept' if skills_kept else 'dropped'}"
    )
    require(not mcp_enabled and skills_kept, "mismatch boundary")

    command_cases = [
        ("./bin/echo-server", None),
        ("../bin/echo-server", "escapes-root"),
    ]
    for command, expected in command_cases:
        got = command_problem(ROOT, command)
        if got is None:
            inside = not escapes_root(ROOT, command)
            print(f"command accept {command} inside={str(inside).lower()}")
        else:
            print(f"command reject {command} reason={got}")
        require(got == expected, f"command {command}")

    cwd_cases = [
        ("data", "not-plugin-relative"),
        ("./data", None),
    ]
    for cwd, expected in cwd_cases:
        got = cwd_problem(ROOT, cwd)
        if got is None:
            inside = not escapes_root(ROOT, cwd)
            print(f"cwd accept {cwd} inside={str(inside).lower()}")
        else:
            print(f"cwd reject {cwd} reason={got}")
        require(got == expected, f"cwd {cwd}")

    print("checks passed")


if __name__ == "__main__":
    main()
