#!/usr/bin/env python3
"""stdio MCP server for io.modelcontextprotocol/skills.

Hand-rolled newline-delimited JSON-RPC. On 2026-10-06 the official SDK
pull requests for SEP-2640 were still open (TypeScript #2818, Python
#3485, Go #1238, C# #1864), and neither typescript-sdk main nor
python-sdk main exposed skills/list. Protocol revision is 2026-07-28:
stdio messages are one JSON object per line, and capabilities arrive
from server/discover rather than initialize.

Flat skill namespace only. Organizational prefixes such as
skill://acme/billing/refunds/SKILL.md are out of scope for this demo.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

PROTOCOL = "2026-07-28"
EXTENSION = "io.modelcontextprotocol/skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# live-note's bytes are a static file. The marker is how the spec spells
# "no stable digest", and the client must refuse to bind an approval to it.
DYNAMIC = frozenset({"live-note"})
CAP = 200
TTL_MS = 300000


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def parse_frontmatter(data: bytes) -> dict:
    text = data.decode("utf-8")
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("unterminated frontmatter")
    parsed: dict[str, str] = {}
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def skill_dirs(root: Path) -> list[Path]:
    found = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if (child / "SKILL.md").is_file():
            found.append(child)
    return found


def files_of(skill_dir: Path) -> list[Path]:
    files = [p for p in skill_dir.rglob("*") if p.is_file()]
    return sorted(files, key=lambda p: p.relative_to(skill_dir).as_posix())


def validate_skill(skill_dir: Path, frontmatter: dict) -> None:
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if not NAME_RE.fullmatch(name) or len(name) > 64:
        raise ValueError(f"invalid skill name: {name!r}")
    if name != skill_dir.name:
        raise ValueError(f"name {name!r} does not match directory {skill_dir.name}")
    if not description or len(description) > 1024:
        raise ValueError(f"invalid description for {name}")


def entry_for(skill_dir: Path) -> dict:
    raw = (skill_dir / "SKILL.md").read_bytes()
    frontmatter = parse_frontmatter(raw)
    validate_skill(skill_dir, frontmatter)
    name = frontmatter["name"]
    uri = f"skill://{name}/SKILL.md"
    if name in DYNAMIC:
        resources: list | str = "dynamic"
    else:
        resources = []
        for path in files_of(skill_dir):
            data = path.read_bytes()
            rel = path.relative_to(skill_dir).as_posix()
            resources.append(
                {
                    "uri": f"skill://{name}/{rel}",
                    "digest": digest_of(data),
                    "size": len(data),
                }
            )
    return {"uri": uri, "frontmatter": frontmatter, "resources": resources}


def lookup(root: Path, name: str) -> Path | None:
    skill_dir = root / name
    if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
        return skill_dir
    return None


def split_skill_uri(uri: str) -> tuple[str, str] | None:
    prefix = "skill://"
    if not isinstance(uri, str) or not uri.startswith(prefix) or uri.endswith("/"):
        return None
    rest = uri[len(prefix) :]
    if not rest or "/" not in rest:
        # skill://refund-check is the directory, not a SKILL.md.
        if rest and "/" not in rest:
            return rest, ""
        return None
    name, rel = rest.split("/", 1)
    return name, rel


def cacheable(payload: dict) -> dict:
    payload["resultType"] = "complete"
    payload["ttlMs"] = TTL_MS
    payload["cacheScope"] = "public"
    return payload


def mime_for(path: Path) -> str:
    if path.suffix == ".md":
        return "text/markdown"
    return "text/plain"


def send(message: dict) -> None:
    line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.buffer.write(line.encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def ok(msg_id, result: dict) -> None:
    send({"jsonrpc": "2.0", "id": msg_id, "result": result})


def fail(msg_id, code: int, message: str) -> None:
    send({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}})


def handle(root: Path, msg: dict) -> None:
    if "id" not in msg:
        return
    msg_id = msg["id"]
    method = msg.get("method")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        fail(msg_id, -32602, "params must be an object")
        return

    if method == "server/discover":
        ok(
            msg_id,
            cacheable(
                {
                    "supportedVersions": [PROTOCOL],
                    "capabilities": {
                        "resources": {},
                        "tools": {},
                        "extensions": {EXTENSION: {"directoryRead": True}},
                    },
                    "instructions": (
                        "Refund workflow: skill://refund-check/SKILL.md. "
                        "Confirm with skills/get before loading."
                    ),
                    "_meta": {
                        "io.modelcontextprotocol/serverInfo": {
                            "name": "refund-tools",
                            "version": "0.1.0",
                        }
                    },
                }
            ),
        )
        return

    if method == "skills/list":
        skills = [entry_for(path) for path in skill_dirs(root)]
        ok(msg_id, cacheable({"skills": skills}))
        return

    if method == "skills/get":
        parsed = split_skill_uri(params.get("uri", ""))
        if parsed is None or parsed[1] != "SKILL.md":
            fail(msg_id, -32602, "params.uri must be a SKILL.md resource URI")
            return
        skill_dir = lookup(root, parsed[0])
        if skill_dir is None:
            fail(msg_id, -32602, f"No skill is served at {params.get('uri')}")
            return
        ok(msg_id, cacheable({"skill": entry_for(skill_dir)}))
        return

    if method == "resources/read":
        parsed = split_skill_uri(params.get("uri", ""))
        if parsed is None or not parsed[1]:
            fail(msg_id, -32602, f"No file is served at {params.get('uri')}")
            return
        name, rel = parsed
        skill_dir = lookup(root, name)
        path = (skill_dir / rel) if skill_dir is not None else None
        if path is None or not path.is_file():
            fail(msg_id, -32602, f"No file is served at {params.get('uri')}")
            return
        data = path.read_bytes()
        ok(
            msg_id,
            cacheable(
                {
                    "contents": [
                        {
                            "uri": params["uri"],
                            "mimeType": mime_for(path),
                            "text": data.decode("utf-8"),
                        }
                    ]
                }
            ),
        )
        return

    if method == "resources/directory/read":
        parsed = split_skill_uri(str(params.get("uri", "")))
        # split_skill_uri returns None for a bare skill://name because of the
        # "/" check. Accept the directory form here.
        uri = params.get("uri", "")
        if isinstance(uri, str) and uri.startswith("skill://") and "/" not in uri[len("skill://") :]:
            parsed = (uri[len("skill://") :], "")
        if parsed is None:
            fail(msg_id, -32602, f"{uri} is not a directory resource")
            return
        name, rel = parsed
        skill_dir = lookup(root, name)
        directory = skill_dir if skill_dir is not None else None
        if directory is not None and rel:
            directory = directory / rel
        if directory is None or not directory.is_dir():
            fail(msg_id, -32602, f"{uri} is not a directory resource")
            return
        children = []
        for child in sorted(directory.iterdir(), key=lambda p: p.name):
            child_rel = child.relative_to(skill_dir).as_posix()
            if child.is_dir():
                children.append(
                    {
                        "uri": f"skill://{name}/{child_rel}",
                        "name": child.name,
                        "mimeType": "inode/directory",
                    }
                )
            elif child.is_file():
                children.append(
                    {
                        "uri": f"skill://{name}/{child_rel}",
                        "name": child.name,
                        "mimeType": mime_for(child),
                    }
                )
        ok(msg_id, {"resultType": "complete", "resources": children})
        return

    if method == "resources/list":
        resources = []
        for skill_dir in skill_dirs(root):
            entry = entry_for(skill_dir)
            for path in files_of(skill_dir):
                rel = path.relative_to(skill_dir).as_posix()
                item = {
                    "uri": f"skill://{entry['frontmatter']['name']}/{rel}",
                    "name": path.name,
                    "mimeType": mime_for(path),
                }
                if rel == "SKILL.md":
                    item["name"] = entry["frontmatter"]["name"]
                    item["description"] = entry["frontmatter"]["description"]
                resources.append(item)
        ok(msg_id, cacheable({"resources": resources}))
        return

    if method == "tools/list":
        ok(
            msg_id,
            cacheable(
                {
                    "tools": [
                        {
                            "name": "check_refund",
                            "description": "Accept a refund amount only when it is at most 200.",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"amount": {"type": "number"}},
                                "required": ["amount"],
                            },
                        }
                    ]
                }
            ),
        )
        return

    if method == "tools/call":
        if params.get("name") != "check_refund":
            fail(msg_id, -32602, "unknown tool")
            return
        arguments = params.get("arguments") or {}
        amount = arguments.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            ok(
                msg_id,
                {
                    "resultType": "complete",
                    "content": [{"type": "text", "text": "amount must be a number"}],
                    "isError": True,
                },
            )
            return
        if amount <= CAP:
            text = f"allowed: {amount} is within the hard cap of {CAP}"
        else:
            text = f"refused: {amount} exceeds the hard cap of {CAP}"
        ok(
            msg_id,
            {
                "resultType": "complete",
                "content": [{"type": "text", "text": text}],
                "isError": False,
            },
        )
        return

    fail(msg_id, -32601, f"method not found: {method}")


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: server.py <skills-dir>", file=sys.stderr)
        sys.exit(2)
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        sys.exit(2)
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        try:
            handle(root, msg)
        except Exception as exc:  # noqa: BLE001 — surface as a JSON-RPC internal error
            if "id" in msg:
                fail(msg["id"], -32603, str(exc))


if __name__ == "__main__":
    main()
