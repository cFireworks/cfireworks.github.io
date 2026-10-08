#!/usr/bin/env python3
"""Minimal Agent Memory Repo dream pass, plus two sessions on one drive.

The seed follows the format in SPEC.md: MEMORY.md, one-line bullets,
`[key: value; key: value]` metadata, and `[[path]]` links from the repo root.
Dreaming in the spec merges duplicates, drops outdated entries, and resolves
contradictions by checking sources. This script is not that agent. It only
does three mechanical checks:

- identical bullet text in one file is a duplicate; keep the later `added`
  date and every `source`
- bullets that share a `pref` key can supersede each other, and only when
  every one of them has an `added` date and the newest date has a single text
- `[[path]]` must resolve to `path.md`, or to `path` when the extension is kept

`pref` is an open key this demo chose. The spec does not define it. A missing
date or a tie is reported and left in place. Git is not asked to pick a winner.

The session half uses a bare repo as the drive. Each session remembers the
revision it checked out. A push is refused when that revision is no longer
the drive's tip. The script then shows git's own non-fast-forward rejection
and, on a same-line edit, the conflict markers.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path("/tmp/agent-memory-dream-demo")
SEED = Path(__file__).resolve().parent / "seed"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
TRAILING_META = re.compile(r"\s+\[([^\[\]]+)\]\s*$")

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "memory-demo",
    "GIT_AUTHOR_EMAIL": "memory-demo@example.com",
    "GIT_COMMITTER_NAME": "memory-demo",
    "GIT_COMMITTER_EMAIL": "memory-demo@example.com",
    "GIT_AUTHOR_DATE": "2026-10-08T08:40:00+08:00",
    "GIT_COMMITTER_DATE": "2026-10-08T08:40:00+08:00",
    "GIT_MERGE_AUTOEDIT": "no",
    "LC_ALL": "C",
    "LANG": "C",
}


@dataclass
class Entry:
    path: str
    line_index: int
    body: str
    brackets: list[dict[str, str]] = field(default_factory=list)

    def meta(self, key: str) -> str | None:
        for bracket in self.brackets:
            if key in bracket:
                return bracket[key]
        return None

    def sources(self) -> list[str]:
        found: list[str] = []
        for bracket in self.brackets:
            source = bracket.get("source")
            if source and source not in found:
                found.append(source)
        return found


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-c", "advice.pushUpdateRejected=false", *args],
        cwd=cwd,
        env=GIT_ENV,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise SystemExit(
            f"FAIL git {' '.join(args)}\n{proc.stdout}{proc.stderr}"
        )
    return proc


def rev(cwd: Path, ref: str = "HEAD") -> str:
    return git(cwd, "rev-parse", ref).stdout.strip()


def short(sha: str) -> str:
    return sha[:7]


def parse_bracket(inner: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for part in inner.split(";"):
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def parse_bullet(text: str) -> tuple[str, list[dict[str, str]]]:
    body = text
    raw_brackets: list[str] = []
    while True:
        match = TRAILING_META.search(body)
        if not match or ":" not in match.group(1):
            break
        raw_brackets.append(match.group(1))
        body = body[: match.start()]
    raw_brackets.reverse()
    return body.strip(), [parse_bracket(item) for item in raw_brackets]


def parse_entries(files: dict[str, list[str]]) -> list[Entry]:
    entries: list[Entry] = []
    for path in sorted(files):
        for index, line in enumerate(files[path]):
            if not line.startswith("- "):
                continue
            body, brackets = parse_bullet(line[2:])
            entries.append(Entry(path, index, body, brackets))
    return entries


def added_day(entry: Entry) -> str | None:
    added = entry.meta("added")
    if not added or not DATE_RE.match(added):
        return None
    try:
        datetime.strptime(added, "%Y-%m-%d")
    except ValueError:
        return None
    return added


def format_entry(entry: Entry, sources: list[str], added: str | None) -> str:
    pref = entry.meta("pref")
    tail: list[str] = []
    if added:
        tail.append(f"added: {added}")
    if pref:
        tail.append(f"pref: {pref}")
    if len(sources) <= 1:
        keys: list[str] = []
        if sources:
            keys.append(f"source: {sources[0]}")
        keys.extend(tail)
        if not keys:
            return f"- {entry.body}"
        return f"- {entry.body} [{'; '.join(keys)}]"
    chunks = [f"[source: {source}]" for source in sources]
    if tail:
        chunks.append("[" + "; ".join(tail) + "]")
    return f"- {entry.body} " + " ".join(chunks)


def apply(files: dict[str, list[str]], edits: dict[tuple[str, int], str | None]) -> None:
    for path in list(files):
        kept: list[str] = []
        for index, line in enumerate(files[path]):
            key = (path, index)
            if key not in edits:
                kept.append(line)
            elif edits[key] is not None:
                kept.append(edits[key])
        files[path] = kept


def merge_duplicates(files: dict[str, list[str]]) -> list[str]:
    grouped: dict[tuple[str, str], list[Entry]] = {}
    for entry in parse_entries(files):
        grouped.setdefault((entry.path, entry.body), []).append(entry)
    edits: dict[tuple[str, int], str | None] = {}
    notes: list[str] = []
    for (path, body), group in sorted(grouped.items()):
        if len(group) < 2:
            continue
        prefs = {entry.meta("pref") for entry in group}
        if len(prefs) > 1:
            notes.append(f"duplicate-pref-mismatch {path} kept=all")
            continue
        dated = [entry for entry in group if added_day(entry)]
        winner = max(dated, key=lambda entry: added_day(entry) or "") if dated else group[0]
        sources: list[str] = []
        for entry in group:
            for source in entry.sources():
                if source not in sources:
                    sources.append(source)
        edits[(path, winner.line_index)] = format_entry(
            winner, sources, added_day(winner)
        )
        for entry in group:
            if entry is not winner:
                edits[(entry.path, entry.line_index)] = None
        notes.append(
            "duplicate "
            f"{path} kept={added_day(winner) or 'undated'} "
            f"sources={len(sources)} dropped_lines={len(group) - 1} "
            f"body={body}"
        )
    apply(files, edits)
    return notes


def supersede(files: dict[str, list[str]]) -> list[str]:
    grouped: dict[str, list[Entry]] = {}
    for entry in parse_entries(files):
        pref = entry.meta("pref")
        if pref:
            grouped.setdefault(pref, []).append(entry)
    edits: dict[tuple[str, int], str | None] = {}
    notes: list[str] = []
    for pref, group in sorted(grouped.items()):
        if len(group) < 2:
            continue
        if any(added_day(entry) is None for entry in group):
            notes.append(f"undated pref={pref} kept={len(group)}")
            continue
        newest = max(added_day(entry) or "" for entry in group)
        bodies = {entry.body for entry in group if added_day(entry) == newest}
        if len(bodies) > 1:
            notes.append(f"same-date pref={pref} date={newest} kept={len(group)}")
            continue
        dropped = 0
        for entry in group:
            if added_day(entry) != newest:
                edits[(entry.path, entry.line_index)] = None
                dropped += 1
        notes.append(f"superseded pref={pref} kept={newest} dropped={dropped}")
    apply(files, edits)
    return notes


def resolve_link(root: Path, target: str) -> Path | None:
    if target.startswith("/") or ".." in Path(target).parts:
        return None
    direct = root / target
    if direct.is_file():
        return direct
    if Path(target).suffix == "":
        markdown = root / f"{target}.md"
        if markdown.is_file():
            return markdown
    return None


def check_links(root: Path) -> list[str]:
    counts: dict[str, int] = {}
    for path in sorted(root.rglob("*.md")):
        if ".git" in path.parts:
            continue
        for target in LINK_RE.findall(path.read_text(encoding="utf-8")):
            counts[target] = counts.get(target, 0) + 1
    notes: list[str] = []
    for target, count in sorted(counts.items()):
        found = resolve_link(root, target)
        if found is None:
            expected = f"{target}.md" if Path(target).suffix == "" else target
            notes.append(f"link [[{target}]] -> {expected} MISSING count={count}")
        else:
            notes.append(
                f"link [[{target}]] -> {found.relative_to(root)} ok count={count}"
            )
    return notes


def write_tree(root: Path, files: dict[str, list[str]]) -> None:
    for path, lines in files.items():
        dest = root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_tree(root: Path) -> dict[str, list[str]]:
    files: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix != ".md":
            continue
        files[path.relative_to(root).as_posix()] = path.read_text(
            encoding="utf-8"
        ).splitlines()
    return files


def copy_seed(dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(SEED, dest, ignore=shutil.ignore_patterns(".git"))


def commit_all(cwd: Path, message: str) -> str | None:
    git(cwd, "add", "-A")
    if git(cwd, "diff", "--cached", "--quiet", check=False).returncode == 0:
        return None
    git(cwd, "commit", "-m", message)
    return rev(cwd)


def init_repo(cwd: Path) -> None:
    git(cwd, "init", "-b", "main")


def dream(repo: Path) -> None:
    files = load_tree(repo)
    for note in merge_duplicates(files):
        print(note)
    for note in supersede(files):
        print(note)
    write_tree(repo, files)
    for note in check_links(repo):
        print(note)
    dreamed = commit_all(repo, "dream: merge duplicates and drop older prefs")
    require(dreamed is not None, "dream made no commit")
    print(f"commit {short(dreamed)} dream")
    diff = git(repo, "diff", "--no-color", "--unified=1", "HEAD~1")
    print(diff.stdout, end="" if diff.stdout.endswith("\n") else "\n")


def remote_tip(cwd: Path) -> str:
    git(cwd, "fetch", "origin")
    return rev(cwd, "origin/main")


def push_or_reject(cwd: Path, base: str) -> str:
    tip = remote_tip(cwd)
    if tip != base:
        print(f"revision check reject checkout={short(base)} remote={short(tip)}")
        pushed = git(cwd, "push", "origin", "HEAD:main", check=False)
        print(pushed.stderr, end="" if pushed.stderr.endswith("\n") else "\n")
        require(pushed.returncode != 0, "stale push was accepted")
        require("non-fast-forward" in pushed.stderr, "push was not a non-fast-forward")
        return "rejected"
    git(cwd, "push", "origin", "HEAD:main")
    print(f"push ok {short(rev(cwd))}")
    return "pushed"


def append_line(path: Path, line: str) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + line + "\n", encoding="utf-8")


def insert_before_index(path: Path, line: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    index = lines.index("## Index")
    lines.insert(index, "")
    lines.insert(index, line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def replace_line(path: Path, old: str, new: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    hits = [index for index, line in enumerate(lines) if line == old]
    require(len(hits) == 1, f"expected one line to replace in {path.name}")
    lines[hits[0]] = new
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sessions(drive: Path, dreamed: Path) -> None:
    work = ROOT / "session-a"
    copy_seed_from_repo(dreamed, work)
    init_repo(work)
    git(work, "remote", "add", "origin", str(drive))
    seed_rev = commit_all(work, "memory seed")
    require(seed_rev is not None, "seed commit missing")
    git(work, "push", "-u", "origin", "main")
    other = ROOT / "session-b"
    git(ROOT, "clone", str(drive), str(other))
    require(rev(work) == rev(other), "sessions diverged at start")
    print(f"drive {short(rev(work))}")

    base_a = rev(work)
    base_b = rev(other)
    print("A append tooling/ports.md")
    append_line(
        work / "tooling" / "ports.md",
        "- 预览端口改到 4321 [source: https://example.com/sessions/14; added: 2026-10-08]",
    )
    commit_all(work, "session A: preview port")
    require(push_or_reject(work, base_a) == "pushed", "A should push")

    print("B insert MEMORY.md")
    insert_before_index(
        other / "MEMORY.md",
        "- 日志里不写令牌 [source: https://example.com/sessions/13; added: 2026-10-08]",
    )
    commit_all(other, "session B: do not log tokens")
    require(push_or_reject(other, base_b) == "rejected", "B should be stale")

    merged = git(other, "merge", "origin/main", "-m", "merge drive into B")
    print(merged.stdout, end="" if merged.stdout.endswith("\n") else "\n")
    combined = (other / "MEMORY.md").read_text(encoding="utf-8")
    ports = (other / "tooling" / "ports.md").read_text(encoding="utf-8")
    require("日志里不写令牌" in combined, "B note missing after clean merge")
    require("预览端口改到 4321" in ports, "A note missing after clean merge")
    require("<<<<<<<" not in combined and "<<<<<<<" not in ports, "clean merge conflicted")
    git(other, "push", "origin", "HEAD:main")
    print(f"clean merge push ok {short(rev(other))}")

    git(work, "fetch", "origin")
    git(work, "merge", "origin/main", "-m", "session A syncs")
    require(rev(work) == rev(other), "sessions not reunited")
    print(f"both at {short(rev(work))}")

    bun = (
        "- 安装依赖用 bun，锁文件是 bun.lock "
        "[source: https://example.com/sessions/5] "
        "[source: https://example.com/sessions/6] "
        "[added: 2026-10-04; pref: package-manager]"
    )
    line_a = (
        "- CI 也用 bun，锁文件仍是 bun.lock "
        "[source: https://example.com/sessions/7; added: 2026-10-07; pref: package-manager]"
    )
    line_b = (
        "- CI 改回 npm，锁文件是 package-lock.json "
        "[source: https://example.com/sessions/8; added: 2026-10-07; pref: package-manager]"
    )
    base_a = rev(work)
    base_b = rev(other)
    print("A replace tooling/package-manager.md")
    replace_line(work / "tooling" / "package-manager.md", bun, line_a)
    commit_all(work, "session A: ci uses bun")
    require(push_or_reject(work, base_a) == "pushed", "A same-line push")
    print("B replace tooling/package-manager.md")
    replace_line(other / "tooling" / "package-manager.md", bun, line_b)
    commit_all(other, "session B: ci uses npm")
    require(push_or_reject(other, base_b) == "rejected", "B same-line stale")
    conflicted = git(other, "merge", "origin/main", "-m", "merge same line", check=False)
    print(conflicted.stdout, end="" if conflicted.stdout.endswith("\n") else "\n")
    print(conflicted.stderr, end="" if conflicted.stderr.endswith("\n") else "\n")
    require(conflicted.returncode != 0, "same-line merge did not conflict")
    hunk = (other / "tooling" / "package-manager.md").read_text(encoding="utf-8")
    print(hunk, end="" if hunk.endswith("\n") else "\n")
    status = git(other, "status", "--short")
    print(status.stdout, end="" if status.stdout.endswith("\n") else "\n")
    require("<<<<<<< HEAD" in hunk and line_b in hunk and line_a in hunk, "hunk missing")
    require("UU tooling/package-manager.md" in status.stdout, "file not unmerged")
    # A failed merge leaves the conflict staged and unstaged. Do not commit it.
    require(rev(other) != rev(work), "conflict was committed over A's revision")


def copy_seed_from_repo(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for path in src.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.is_file():
            target = dest / path.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def main() -> None:
    print(f"python {sys.version.split()[0]}")
    print(f"root {ROOT}")
    if ROOT.exists():
        shutil.rmtree(ROOT)
    ROOT.mkdir()
    repo = ROOT / "dream"
    copy_seed(repo)
    init_repo(repo)
    seeded = commit_all(repo, "seed memory")
    require(seeded is not None, "seed")
    print("== dream ==")
    print(f"seed {short(seeded)}")
    dream(repo)
    print("== sessions ==")
    drive = ROOT / "drive.git"
    git(ROOT, "init", "--bare", "-b", "main", str(drive))
    sessions(drive, repo)
    print("checks passed")


if __name__ == "__main__":
    main()
