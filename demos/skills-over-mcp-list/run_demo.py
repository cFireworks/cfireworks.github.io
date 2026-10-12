#!/usr/bin/env python3
"""In-process mock of Skills over MCP. No network, no Cloudflare OAuth.

Two servers share one URI and one skill name on purpose. Only the server that
declares io.modelcontextprotocol/skills answers skills/list and skills/get.
Skill files are still ordinary resources/read targets.
"""

from __future__ import annotations

import hashlib
import sys

EXTENSION_ID = "io.modelcontextprotocol/skills"
TTL_MS = 300000
CACHE_SCOPE = "public"
PAGE_SIZE = 1


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def parse_frontmatter(text: str) -> dict[str, str]:
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


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


class File:
    def __init__(self, uri: str, text: str, name: str, mime: str = "text/markdown") -> None:
        self.uri = uri
        self.text = text
        self.raw = text.encode("utf-8")
        self.name = name
        self.mime = mime
        self.size = len(self.raw)
        self.digest = digest_of(self.raw)


class Skill:
    def __init__(self, skill_md: File, files: list[File], listed: bool = True) -> None:
        self.skill_md = skill_md
        self.files = files
        self.listed = listed
        self.frontmatter = parse_frontmatter(skill_md.text)
        leaf = skill_md.uri.removesuffix("/SKILL.md").rsplit("/", 1)[-1]
        require(self.frontmatter["name"] == leaf, f"name {self.frontmatter['name']} != {leaf}")
        require(any(item.uri == skill_md.uri for item in files), "manifest missing SKILL.md")


def skill_entry(skill: Skill) -> dict:
    return {
        "uri": skill.skill_md.uri,
        "frontmatter": dict(skill.frontmatter),
        "resources": [
            {"uri": item.uri, "digest": item.digest, "size": item.size} for item in skill.files
        ],
    }


class Server:
    """Minimal JSON-RPC-shaped dispatcher. Calls stay in this process."""

    def __init__(self, info_name: str, skills: list[Skill], declare: bool, instructions: str) -> None:
        self.info_name = info_name
        self.skills = skills
        self.declare = declare
        self.instructions = instructions
        self.by_uri = {item.uri: item for skill in skills for item in skill.files}
        self.by_skill_uri = {skill.skill_md.uri: skill for skill in skills}

    def discover(self) -> dict:
        capabilities: dict = {"resources": {}}
        if self.declare:
            capabilities["extensions"] = {EXTENSION_ID: {"directoryRead": False}}
        return {
            "protocolVersion": "2026-07-28",
            "serverInfo": {"name": self.info_name, "version": "0"},
            "capabilities": capabilities,
            "instructions": self.instructions,
        }

    def call(self, method: str, params: dict | None = None) -> dict:
        params = params or {}
        if method == "skills/list":
            if not self.declare:
                return self._error(-32601, "Method not found")
            return {"result": self._list(params.get("cursor"))}
        if method == "skills/get":
            if not self.declare:
                return self._error(-32601, "Method not found")
            return self._get(params["uri"])
        if method == "resources/read":
            return self._read(params["uri"])
        if method == "resources/list":
            return {"result": self._resources()}
        if method == "resources/directory/read":
            return self._error(-32601, "Method not found")
        return self._error(-32601, "Method not found")

    def _list(self, cursor: str | None) -> dict:
        listed = [skill for skill in self.skills if skill.listed]
        start = 0 if not cursor else int(cursor)
        page = listed[start : start + PAGE_SIZE]
        result = {
            "resultType": "complete",
            "skills": [skill_entry(skill) for skill in page],
            "ttlMs": TTL_MS,
            "cacheScope": CACHE_SCOPE,
        }
        if start + PAGE_SIZE < len(listed):
            result["nextCursor"] = str(start + PAGE_SIZE)
        return result

    def _get(self, uri: str) -> dict:
        skill = self.by_skill_uri.get(uri)
        if skill is None:
            return self._error(-32602, f"No skill is served at {uri}")
        return {
            "result": {
                "resultType": "complete",
                "skill": skill_entry(skill),
                "ttlMs": TTL_MS,
                "cacheScope": CACHE_SCOPE,
            }
        }

    def _read(self, uri: str) -> dict:
        item = self.by_uri.get(uri)
        if item is None:
            return self._error(-32602, f"Unknown resource {uri}")
        return {
            "result": {
                "resultType": "complete",
                "contents": [{"uri": item.uri, "mimeType": item.mime, "text": item.text}],
                "ttlMs": TTL_MS,
                "cacheScope": CACHE_SCOPE,
            }
        }

    def _resources(self) -> dict:
        resources = []
        for item in self.by_uri.values():
            resources.append(
                {"uri": item.uri, "name": item.name, "mimeType": item.mime}
            )
        resources.sort(key=lambda row: row["uri"])
        return {
            "resultType": "complete",
            "resources": resources,
            "ttlMs": TTL_MS,
            "cacheScope": CACHE_SCOPE,
        }

    @staticmethod
    def _error(code: int, message: str) -> dict:
        return {"error": {"code": code, "message": message}}


def cache_line(result: dict, cursor_key: str = "nextCursor") -> str:
    cursor = result.get(cursor_key, "")
    return (
        f"resultType={result['resultType']} ttlMs={result['ttlMs']} "
        f"cacheScope={result['cacheScope']} {cursor_key}={cursor}"
    )


def verify_read(skill: Skill, uri: str, result: dict) -> str:
    require(result["resultType"] == "complete", "read resultType")
    require(result["ttlMs"] == TTL_MS and result["cacheScope"] == CACHE_SCOPE, "read cache")
    text = result["contents"][0]["text"]
    raw = text.encode("utf-8")
    meta = next(item for item in skill.files if item.uri == uri)
    require(len(raw) == meta.size, f"size {len(raw)} != {meta.size}")
    require(digest_of(raw) == meta.digest, "digest mismatch")
    return f"bytes={len(raw)} {meta.digest} size=match digest=match"


def aware(server: Server, host_label: str) -> None:
    discovered = server.discover()
    extensions = discovered["capabilities"].get("extensions", {})
    settings = extensions.get(EXTENSION_ID)
    require(settings is not None, "aware client expected the extension")
    require(settings.get("directoryRead") is False, "directoryRead")
    print(
        f"discover host={host_label} serverInfo.name={discovered['serverInfo']['name']} "
        f"extension={EXTENSION_ID} directoryRead=false"
    )
    print("directory read not called")

    cursor = None
    page = 1
    seen: list[dict] = []
    while True:
        response = server.call("skills/list", {} if cursor is None else {"cursor": cursor})
        result = response["result"]
        require(result["resultType"] == "complete", "list resultType")
        require(result["ttlMs"] == TTL_MS and result["cacheScope"] == CACHE_SCOPE, "list cache")
        require(len(result["skills"]) <= PAGE_SIZE, "page larger than PAGE_SIZE")
        print(f"skills/list page={page} {cache_line(result)} count={len(result['skills'])}")
        for entry in result["skills"]:
            require(
                any(item["uri"] == entry["uri"] for item in entry["resources"]),
                "SKILL.md missing from manifest",
            )
            print(
                f"skill identity={host_label} {entry['uri']} "
                f"name={entry['frontmatter']['name']} files={len(entry['resources'])}"
            )
            seen.append(entry)
        cursor = result.get("nextCursor")
        if not cursor:
            break
        page += 1

    names = [entry["frontmatter"]["name"] for entry in seen]
    require(names.count("workers") == 2, "expected two skills labeled workers")
    uris = [entry["uri"] for entry in seen]
    require(len(uris) == len(set(uris)), "URIs collided inside one server")
    print(f"names collide label=workers count={names.count('workers')} uris={len(set(uris))}")

    pointed = "skill://products/workers/SKILL.md"
    require(pointed in discovered["instructions"], "instructions missing skill URI")
    got = server.call("skills/get", {"uri": pointed})["result"]
    skill = got["skill"]
    require(got["resultType"] == "complete", "get resultType")
    require(got["ttlMs"] == TTL_MS and got["cacheScope"] == CACHE_SCOPE, "get cache")
    listed = next(entry for entry in seen if entry["uri"] == pointed)
    require(skill["resources"] == listed["resources"], "get manifest != list manifest")
    manifest = {item["uri"]: item for item in skill["resources"]}
    print(
        f"skills/get {skill['uri']} files={len(skill['resources'])} "
        f"SKILL.md size={manifest[pointed]['size']} {manifest[pointed]['digest']}"
    )

    body = server.call("resources/read", {"uri": pointed})["result"]
    held = server.by_skill_uri[pointed]
    print(f"resources/read {pointed} {verify_read(held, pointed, body)}")
    parsed = parse_frontmatter(body["contents"][0]["text"])
    require(parsed == skill["frontmatter"], "frontmatter mismatch")
    print(f"frontmatter fields={','.join(parsed)} match=yes")

    support = "skill://products/workers/references/endpoints.md"
    require(support in manifest, "relative target not in manifest")
    support_body = server.call("resources/read", {"uri": support})["result"]
    print(f"resources/read {support} {verify_read(held, support, support_body)}")

    missing = server.call("skills/get", {"uri": "skill://missing/SKILL.md"})
    require(missing["error"]["code"] == -32602, "missing skill code")
    print(f"skills/get missing error={missing['error']['code']}")


def naive(server: Server, host_label: str) -> None:
    discovered = server.discover()
    print(
        f"naive host={host_label} serverInfo.name={discovered['serverInfo']['name']} "
        "reads-extensions=no methods=resources/list,resources/read"
    )
    result = server.call("resources/list")["result"]
    print(f"resources/list count={len(result['resources'])} {cache_line(result, 'nextCursor')}")
    for item in result["resources"]:
        require("digest" not in item and "frontmatter" not in item, "naive row looked like a skill")
        print(f"resource {item['uri']} name={item['name']} mime={item['mimeType']}")
    first = result["resources"][0]["uri"]
    body = server.call("resources/read", {"uri": first})["result"]
    text = body["contents"][0]["text"]
    print(f"resources/read {first} bytes={len(text.encode('utf-8'))} skill-entry=no")


def main() -> None:
    workers = File(
        "skill://products/workers/SKILL.md",
        "---\n"
        "name: workers\n"
        "description: Read the endpoint note before calling search or execute.\n"
        "---\n"
        "\n"
        "# Workers\n"
        "\n"
        "Read `references/endpoints.md`, then call search. Do not invent endpoint names.\n",
        "workers",
    )
    endpoints = File(
        "skill://products/workers/references/endpoints.md",
        "# Endpoints\n"
        "\n"
        "search finds an operation. execute runs the one you picked.\n",
        "endpoints.md",
    )
    docs = File(
        "skill://docs/workers/SKILL.md",
        "---\n"
        "name: workers\n"
        "description: Explain the docs page. Same label, different URI.\n"
        "---\n"
        "\n"
        "# Workers docs\n"
        "\n"
        "This file is a different skill. The name matches. The URI does not.\n",
        "workers",
    )
    plain = File(
        "skill://products/workers/SKILL.md",
        "---\n"
        "name: workers\n"
        "description: A markdown file on a server that does not declare the extension.\n"
        "---\n"
        "\n"
        "# Not a listed skill\n"
        "\n"
        "This server does not implement skills/list. The bytes are still a resource.\n",
        "workers",
    )

    edge = Server(
        "mock-edge",
        [Skill(workers, [workers, endpoints]), Skill(docs, [docs])],
        declare=True,
        instructions="Workflow: skill://products/workers/SKILL.md. Confirm with skills/get before loading.",
    )
    other = Server(
        "mock-docs",
        [Skill(plain, [plain])],
        declare=False,
        instructions="Read the resource if you want the bytes. There is no skills catalog.",
    )

    print(f"python {sys.version.split()[0]}")
    print("transport in-process mock")
    aware(edge, "edge-api")
    probed = edge.call("resources/directory/read", {"uri": "skill://products/workers"})
    require(probed["error"]["code"] == -32601, "directory read should be absent")
    print(f"probe resources/directory/read error={probed['error']['code']}")
    naive(edge, "edge-api")

    discovered = other.discover()
    require(EXTENSION_ID not in discovered["capabilities"].get("extensions", {}), "plain declared")
    print(
        f"discover host=plain-docs serverInfo.name={discovered['serverInfo']['name']} "
        "extension=absent"
    )
    refused = other.call("skills/list")
    require(refused["error"]["code"] == -32601, "plain skills/list")
    print(f"skills/list error={refused['error']['code']} message={refused['error']['message']}")
    naive(other, "plain-docs")

    edge_key = "edge-api skill://products/workers/SKILL.md"
    plain_key = "plain-docs skill://products/workers/SKILL.md"
    require(edge_key != plain_key, "identity collapsed")
    require(workers.digest != plain.digest, "same bytes on both servers")
    print(f"identity {edge_key}")
    print(f"identity {plain_key}")
    print(f"same-uri digest edge={workers.digest}")
    print(f"same-uri digest plain={plain.digest}")
    print("checks passed")


if __name__ == "__main__":
    main()
