#!/usr/bin/env python3
"""Read-only check for instruction files and a few config lines.

Default mode audits the fixtures in this directory, then checks two temporary
trees: a clean one, and one instruction file that is only a symlink. It does
not read the symlink target. It does not write the files it audits, does not
start a shell, and does not use the network.

Pass ``--downloads`` to audit another tree. In that mode the process exits 1
when it finds something to review, and 0 when it does not. The package name
``function-color`` is only a search string.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 1_048_576
INSTRUCTION_NAMES = {"agents.md", "claude.md"}
NEEDLE = "function-color"
DEMO_ALLOW = frozenset({"local-docs"})
HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"


@dataclass(frozen=True)
class Item:
    kind: str
    detail: str


def bounded_read(path: Path) -> tuple[bytes, bool]:
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    truncated = len(data) > MAX_BYTES
    return data[:MAX_BYTES], truncated


def needle_count(data: bytes) -> int:
    return data.count(NEEDLE.encode("ascii"))


def walk_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise SystemExit(f"not a directory: {root}")
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        kept: list[str] = []
        for name in dirnames:
            if not Path(dirpath, name).is_symlink():
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            found.append(Path(dirpath) / name)
    found.sort()
    return found


def scan_tree(root: Path, scan_ioc: bool) -> list[Item]:
    items: list[Item] = []
    root = root.resolve() if not root.is_symlink() else root
    for path in walk_files(root):
        rel = path.relative_to(root).as_posix()
        is_instruction = path.name.casefold() in INSTRUCTION_NAMES
        if path.is_symlink():
            if is_instruction:
                items.append(Item("instruction-symlink", rel))
            continue
        if not path.is_file():
            continue
        if is_instruction:
            size = path.stat().st_size
            data, truncated = bounded_read(path)
            hits = needle_count(data)
            note = "truncated" if truncated else "full"
            items.append(
                Item(
                    "instruction",
                    f"{rel} bytes={size} read={note} {NEEDLE}={hits}",
                )
            )
            continue
        if scan_ioc:
            data, truncated = bounded_read(path)
            hits = needle_count(data)
            if hits:
                flag = " truncated" if truncated else ""
                items.append(Item("ioc-path", f"{rel} hits={hits}{flag}"))
    return items


def scan_config(path: Path, allow_mcp: frozenset[str]) -> list[Item]:
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f"config is not a regular file: {path}")
    data, truncated = bounded_read(path)
    text = data.decode("utf-8", errors="replace")
    items: list[Item] = []
    if truncated:
        items.append(Item("config-truncated", path.as_posix()))
    for number, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        interesting = (
            "mcp_servers" in lowered
            or "anthropic_base_url" in lowered
            or "chatgpt_base_url" in lowered
            or NEEDLE in lowered
        )
        if not interesting:
            continue
        label = "review"
        if NEEDLE in lowered:
            label = "ioc-line"
        elif "mcp_servers." in lowered or "[mcp_servers." in lowered:
            name = server_name(line)
            if name is not None and name in allow_mcp:
                label = "allowed"
            else:
                label = "unexpected"
        elif "anthropic_base_url" in lowered or "chatgpt_base_url" in lowered:
            label = "unexpected"
        items.append(Item(label, f"{path.name}:{number}: {line}"))
    return items


def server_name(line: str) -> str | None:
    start = line.lower().find("[mcp_servers.")
    if start < 0:
        return None
    rest = line[start + len("[mcp_servers.") :]
    end = rest.find("]")
    if end <= 0:
        return None
    return rest[:end].strip()


def render(title: str, items: list[Item]) -> str:
    lines = [f"== {title} =="]
    if not items:
        lines.append("(none)")
        return "\n".join(lines)
    for item in items:
        lines.append(f"{item.kind} {item.detail}")
    return "\n".join(lines)


def audit(
    downloads: Path,
    codex_config: Path | None,
    claude_settings: list[Path],
    allow_mcp: frozenset[str],
    scan_ioc: bool,
) -> list[Item]:
    items = scan_tree(downloads, scan_ioc=scan_ioc)
    if codex_config is not None:
        items.extend(scan_config(codex_config, allow_mcp))
    for settings in claude_settings:
        items.extend(scan_config(settings, allow_mcp))
    return items


def demo_report() -> str:
    downloads = FIXTURES / "downloads"
    codex = FIXTURES / "codex" / "config.toml"
    claude = FIXTURES / "claude" / "settings.json"
    items = audit(downloads, codex, [claude], DEMO_ALLOW, scan_ioc=True)
    expect = [
        Item("instruction", "AGENTS.md bytes=75 read=full function-color=0"),
        Item(
            "instruction",
            "nested/CLAUDE.md bytes=81 read=full function-color=0",
        ),
        Item("ioc-path", "notes.txt hits=1"),
        Item("allowed", "config.toml:5: [mcp_servers.local-docs]"),
        Item("unexpected", "config.toml:8: [mcp_servers.project-tools]"),
        Item(
            "unexpected",
            'config.toml:11: chatgpt_base_url = "https://example.invalid/codex"',
        ),
        Item(
            "unexpected",
            'settings.json:3:     "ANTHROPIC_BASE_URL": "https://example.invalid/gateway"',
        ),
    ]
    if items != expect:
        rendered = render("fixture", items)
        raise SystemExit(f"fixture mismatch\n{rendered}\nexpected\n{expect}")

    clean = audit_clean_tree()
    if clean:
        raise SystemExit(f"clean tree was not clean: {clean}")

    link_items, leaked = audit_symlink_tree()
    if link_items != [Item("instruction-symlink", "AGENTS.md")]:
        raise SystemExit(f"symlink result: {link_items}")
    if leaked:
        raise SystemExit("symlink target was printed")

    parts = [
        f"python {sys.version.split()[0]}",
        f"downloads {downloads.relative_to(HERE).as_posix()}",
        f"allow-mcp {','.join(sorted(DEMO_ALLOW))}",
        render("fixture", items),
        "== clean ==",
        "(none)",
        "== symlink ==",
        "instruction-symlink AGENTS.md",
        "target-printed no",
        "DEMO OK",
    ]
    return "\n".join(parts) + "\n"


def audit_clean_tree() -> list[Item]:
    with tempfile.TemporaryDirectory(prefix="downloads-audit-clean-") as tmp:
        root = Path(tmp)
        downloads = root / "Downloads"
        downloads.mkdir()
        (downloads / "readme.txt").write_text("hello\n", encoding="utf-8")
        codex = root / "config.toml"
        codex.write_text('model = "demo"\n', encoding="utf-8")
        settings = root / "settings.json"
        settings.write_text("{}\n", encoding="utf-8")
        return audit(downloads, codex, [settings], frozenset(), scan_ioc=True)


def audit_symlink_tree() -> tuple[list[Item], bool]:
    sentinel = "SYMLINK_TARGET_SENTINEL_DO_NOT_PRINT"
    with tempfile.TemporaryDirectory(prefix="downloads-audit-link-") as tmp:
        root = Path(tmp)
        target = root / "outside.txt"
        target.write_text(sentinel + "\n", encoding="utf-8")
        downloads = root / "Downloads"
        downloads.mkdir()
        link = downloads / "AGENTS.md"
        link.symlink_to(target)
        items = audit(downloads, None, [], frozenset(), scan_ioc=True)
        leaked = any(sentinel in item.detail for item in items)
        return items, leaked


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", type=Path)
    parser.add_argument("--codex-config", type=Path)
    parser.add_argument("--claude-settings", type=Path, action="append")
    parser.add_argument("--allow-mcp", action="append", default=[])
    parser.add_argument("--scan-ioc", action="store_true")
    return parser.parse_args(argv)


def real_report(args: argparse.Namespace) -> tuple[str, int]:
    settings = args.claude_settings or []
    items = audit(
        args.downloads,
        args.codex_config,
        settings,
        frozenset(args.allow_mcp),
        scan_ioc=args.scan_ioc,
    )
    text = render("audit", items) + "\n"
    return text, (1 if items else 0)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    custom = any(
        value is not None
        for value in (args.downloads, args.codex_config, args.claude_settings)
    )
    if not custom:
        sys.stdout.write(demo_report())
        return 0
    if args.downloads is None:
        raise SystemExit("--downloads is required when auditing a real tree")
    text, code = real_report(args)
    sys.stdout.write(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
