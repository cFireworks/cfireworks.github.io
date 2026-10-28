#!/usr/bin/env python3
"""Decide which extension surface fits a question, then measure disclosure.

The three surfaces are a local encoding of one decision table:

- MCP when there is no shell, when each operation needs its own grant,
  or when the job is a named read rather than a pipeline
- CLI when a shell is present and the job is a pipeline, and also when
  a skill needs commands to wrap
- Skills when the job needs a procedure, not just a callable

Token search does not change the recommendation. A catalog whose only
tools are ``search`` and ``execute`` is flagged. Nothing here installs a
package, opens a socket, or reads an API key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
ORDER = ("mcp", "cli", "skills")
CLI_LINE = "ax experiments list --project demo --output json"
WRAPS = (
    "ax experiments list",
    "ax experiments compare",
)


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def decide(case: dict) -> tuple[list[str], list[str]]:
    chosen: set[str] = set()
    notes: list[str] = []
    shell = case["has_shell"]
    grants = case["needs_per_tool_grants"]
    pipeline = case["job_is_pipeline"]
    howto = case["needs_procedural_howto"]

    if pipeline and not shell:
        notes.append("pipeline without shell; cli unavailable")

    if not shell:
        chosen.add("mcp")
        notes.append("no shell")
    elif grants:
        chosen.add("mcp")
        notes.append("per-tool grants")
    elif not pipeline:
        chosen.add("mcp")
        notes.append("named read; shell present but unused")

    if shell and pipeline:
        chosen.add("cli")
        notes.append("pipeline")

    if howto:
        chosen.add("skills")
        if shell:
            chosen.add("cli")
            notes.append("skill wraps cli")
        else:
            notes.append("skill text only; calls stay on mcp")

    if not case["tool_search"]:
        notes.append("tool search off does not change the surface")

    ordered = [name for name in ORDER if name in chosen]
    require(ordered, f"empty recommendation for {case['id']}")
    return ordered, notes


def flag(value: bool) -> str:
    return "1" if value else "0"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def card_bytes(name: str, description: str) -> int:
    return len(f"{name}\n{description}".encode("utf-8"))


def full_bytes(tool: dict) -> int:
    payload = json.dumps(tool, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return len(payload.encode("utf-8"))


def parse_frontmatter(text: str) -> dict[str, str]:
    require(text.startswith("---\n"), "skill frontmatter open")
    end = text.find("\n---\n", 4)
    require(end > 0, "skill frontmatter close")
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, value = line.split(": ", 1)
        meta[key] = value
    return meta


def print_case(case: dict) -> None:
    surfaces, notes = decide(case)
    print(
        f"{case['id']} shell={flag(case['has_shell'])} "
        f"grants={flag(case['needs_per_tool_grants'])} "
        f"pipeline={flag(case['job_is_pipeline'])} "
        f"howto={flag(case['needs_procedural_howto'])} "
        f"tool_search={flag(case['tool_search'])} "
        f"-> {','.join(surfaces)} | {'; '.join(notes)}"
    )


def check_catalog(path: Path, expect_generic: bool) -> tuple[int, int]:
    catalog = load_json(path)
    tools = catalog["tools"]
    names = [tool["name"] for tool in tools]
    card_sum = 0
    full_sum = 0
    for tool in tools:
        hint = tool["annotations"]["readOnlyHint"]
        require(isinstance(hint, bool), f"{tool['name']} readOnlyHint")
        card = card_bytes(tool["name"], tool["description"])
        full = full_bytes(tool)
        require(card < full, f"{tool['name']} card is not smaller than schema")
        card_sum += card
        full_sum += full
        print(
            f"tool {tool['name']} readonly={flag(hint)} card={card} full={full}"
        )
    generic = sorted(names) == ["execute", "search"]
    require(generic is expect_generic, f"generic pair mismatch for {path.name}")
    label = "wrapper" if expect_generic else "catalog"
    shown = ",".join(names)
    print(
        f"{label} tools={len(tools)} names={shown} "
        f"generic_pair={flag(generic)} card_sum={card_sum} full_sum={full_sum}"
    )
    require(card_sum < full_sum, f"{label} card sum")
    return card_sum, full_sum


def main() -> None:
    print(f"python {sys.version.split()[0]}")
    print("measure tool=canonical-json skill=raw-file cli=raw-file")
    print("network=not_used")

    cases = [
        {
            "id": "desktop-no-shell",
            "has_shell": False,
            "needs_per_tool_grants": False,
            "job_is_pipeline": False,
            "needs_procedural_howto": False,
            "tool_search": True,
        },
        {
            "id": "ci-cron",
            "has_shell": True,
            "needs_per_tool_grants": False,
            "job_is_pipeline": True,
            "needs_procedural_howto": False,
            "tool_search": True,
        },
        {
            "id": "editor-grants",
            "has_shell": True,
            "needs_per_tool_grants": True,
            "job_is_pipeline": False,
            "needs_procedural_howto": False,
            "tool_search": True,
        },
        {
            "id": "shell-read",
            "has_shell": True,
            "needs_per_tool_grants": False,
            "job_is_pipeline": False,
            "needs_procedural_howto": False,
            "tool_search": True,
        },
        {
            "id": "ci-with-grants",
            "has_shell": True,
            "needs_per_tool_grants": True,
            "job_is_pipeline": True,
            "needs_procedural_howto": False,
            "tool_search": True,
        },
        {
            "id": "cron-howto",
            "has_shell": True,
            "needs_per_tool_grants": False,
            "job_is_pipeline": True,
            "needs_procedural_howto": True,
            "tool_search": True,
        },
        {
            "id": "desktop-howto",
            "has_shell": False,
            "needs_per_tool_grants": False,
            "job_is_pipeline": False,
            "needs_procedural_howto": True,
            "tool_search": True,
        },
        {
            "id": "editor-howto",
            "has_shell": True,
            "needs_per_tool_grants": False,
            "job_is_pipeline": False,
            "needs_procedural_howto": True,
            "tool_search": True,
        },
        {
            "id": "search-off",
            "has_shell": False,
            "needs_per_tool_grants": False,
            "job_is_pipeline": False,
            "needs_procedural_howto": False,
            "tool_search": False,
        },
    ]

    print("== decide ==")
    seen = [case["id"] for case in cases]
    require(len(seen) == len(set(seen)), "duplicate case id")
    for case in cases:
        print_case(case)

    same = decide(cases[0])
    off = decide(cases[-1])
    require(same[0] == off[0], "tool search changed the surface")
    require(
        cases[0]["has_shell"] == cases[-1]["has_shell"]
        and cases[0]["needs_per_tool_grants"] == cases[-1]["needs_per_tool_grants"]
        and cases[0]["job_is_pipeline"] == cases[-1]["job_is_pipeline"]
        and cases[0]["needs_procedural_howto"] == cases[-1]["needs_procedural_howto"],
        "search-off is not the desktop case",
    )

    print("== disclosure ==")
    check_catalog(FIXTURES / "tools.json", expect_generic=False)
    check_catalog(FIXTURES / "wrapper.json", expect_generic=True)

    help_text = (FIXTURES / "ax-help.txt").read_text(encoding="utf-8")
    help_bytes = len(help_text.encode("utf-8"))
    line_bytes = len(CLI_LINE.encode("utf-8"))
    require(help_text.count(CLI_LINE) == 1, "cli line count")
    require(line_bytes < help_bytes, "cli line is not smaller than help")
    print(f"cli line={line_bytes} help={help_bytes}")

    skill_path = FIXTURES / "skills" / "compare-experiments" / "SKILL.md"
    skill_raw = skill_path.read_bytes()
    meta = parse_frontmatter(skill_raw.decode("utf-8"))
    require(meta["name"] == skill_path.parent.name, "skill name matches directory")
    skill_card = card_bytes(meta["name"], meta["description"])
    require(skill_card < len(skill_raw), "skill card is not smaller than file")
    body = skill_raw.decode("utf-8")
    for command in WRAPS:
        require(command in body, f"skill missing {command}")
        require(command in help_text, f"help missing {command}")
    print(
        f"skill {meta['name']} card={skill_card} body={len(skill_raw)} "
        f"wraps={','.join(WRAPS)}"
    )
    print("checks passed")


if __name__ == "__main__":
    main()
