#!/usr/bin/env python3
"""Drive the demo skills server and check the spec's digest rules.

Copies the skill tree to a temp directory, talks newline-delimited JSON-RPC
over stdio, then mutates the copy. The approval key is the host label plus
the skill URI, never serverInfo.name.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HOST_LABEL = "demo-skills"
META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {
        "name": "skills-digest-client",
        "version": "0.1.0",
    },
    "io.modelcontextprotocol/clientCapabilities": {},
}


def digest_of(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def parse_frontmatter(text: str) -> dict:
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


class Session:
    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc
        self.next_id = 1

    def request(self, method: str, params: dict | None = None) -> dict:
        body = {
            "jsonrpc": "2.0",
            "id": self.next_id,
            "method": method,
            "params": {"_meta": META, **(params or {})},
        }
        self.next_id += 1
        assert self.proc.stdin is not None and self.proc.stdout is not None
        line = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
        self.proc.stdin.write(line + b"\n")
        self.proc.stdin.flush()
        raw = self.proc.stdout.readline()
        if not raw:
            err = self.proc.stderr.read().decode() if self.proc.stderr else ""
            raise RuntimeError(f"server closed stdout\n{err}")
        return json.loads(raw)


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def main() -> None:
    here = Path(__file__).resolve().parent
    server = here / "server.py"
    source = here / "skills"
    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(message)

    with tempfile.TemporaryDirectory(prefix="mcp-skills-") as tmp:
        root = Path(tmp) / "skills"
        shutil.copytree(source, root)
        proc = subprocess.Popen(
            [sys.executable, str(server), str(root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            session = Session(proc)
            discovered = session.request("server/discover")
            result = discovered["result"]
            extension = result["capabilities"]["extensions"]["io.modelcontextprotocol/skills"]
            server_name = result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"]
            log(
                "discover "
                f"directoryRead={str(extension['directoryRead']).lower()} "
                f"serverInfo.name={server_name} host_label={HOST_LABEL}"
            )
            log(f"instructions={result['instructions']}")
            require(extension["directoryRead"] is True, "directoryRead")
            require(server_name != HOST_LABEL, "host label must not copy serverInfo.name")

            listed = session.request("skills/list")["result"]["skills"]
            log("skills/list " + " ".join(
                f"{item['frontmatter']['name']}="
                + (item["resources"] if item["resources"] == "dynamic" else str(len(item["resources"])))
                for item in listed
            ))
            require(len(listed) == 2, "expected two skills")

            refund = session.request(
                "skills/get", {"uri": "skill://refund-check/SKILL.md"}
            )["result"]["skill"]
            resources = refund["resources"]
            require(isinstance(resources, list) and len(resources) == 2, "refund manifest")
            by_uri = {item["uri"]: item for item in resources}
            log(
                "skills/get refund-check "
                + " ".join(f"{item['uri']} size={item['size']} {item['digest']}" for item in resources)
            )

            # Held entry. Approval is bound to this set, not to the server name.
            approval = {
                "origin": HOST_LABEL,
                "uri": refund["uri"],
                "resources": [(item["uri"], item["digest"]) for item in resources],
            }
            log(
                "approval "
                f"origin={approval['origin']} files={len(approval['resources'])} "
                f"allowed-tools={refund['frontmatter'].get('allowed-tools')} granted=false"
            )
            require(refund["frontmatter"].get("allowed-tools") == "check_refund", "allowed-tools")

            skill_body = session.request(
                "resources/read", {"uri": "skill://refund-check/SKILL.md"}
            )["result"]["contents"][0]["text"]
            skill_bytes = skill_body.encode("utf-8")
            skill_meta = by_uri["skill://refund-check/SKILL.md"]
            skill_digest = digest_of(skill_bytes)
            frontmatter = parse_frontmatter(skill_body)
            log(
                "resources/read SKILL.md "
                f"bytes={len(skill_bytes)} digest={skill_digest} "
                f"match={str(skill_digest == skill_meta['digest'] and len(skill_bytes) == skill_meta['size']).lower()} "
                f"frontmatter_match={str(frontmatter == refund['frontmatter']).lower()}"
            )
            require(skill_digest == skill_meta["digest"], "skill digest")
            require(len(skill_bytes) == skill_meta["size"], "skill size")
            require(frontmatter == refund["frontmatter"], "frontmatter")

            policy_uri = "skill://refund-check/references/policy.md"
            policy_body = session.request("resources/read", {"uri": policy_uri})["result"]["contents"][0]["text"]
            policy_bytes = policy_body.encode("utf-8")
            policy_meta = by_uri[policy_uri]
            policy_digest = digest_of(policy_bytes)
            log(
                "resources/read policy.md "
                f"bytes={len(policy_bytes)} digest={policy_digest} "
                f"match={str(policy_digest == policy_meta['digest'] and len(policy_bytes) == policy_meta['size']).lower()}"
            )
            require(policy_digest == policy_meta["digest"], "policy digest")

            children = session.request(
                "resources/directory/read",
                {"uri": "skill://refund-check/references"},
            )["result"]["resources"]
            log("directory/read references " + ",".join(item["name"] for item in children))
            require([item["name"] for item in children] == ["policy.md"], "directory children")

            missing = session.request("skills/get", {"uri": "skill://missing/SKILL.md"})
            log(f"skills/get missing error={missing['error']['code']} message={missing['error']['message']}")
            require(missing["error"]["code"] == -32602, "unknown skill")

            live = session.request("skills/get", {"uri": "skill://live-note/SKILL.md"})["result"]["skill"]
            log(f"skills/get live-note resources={live['resources']} approval=declined")
            require(live["resources"] == "dynamic", "dynamic marker")

            for amount in (150, 500):
                called = session.request(
                    "tools/call",
                    {"name": "check_refund", "arguments": {"amount": amount}},
                )["result"]["content"][0]["text"]
                log(f"tools/call check_refund amount={amount} text={called}")
            require("allowed: 150" in session_text(lines), "allow 150")

            extra = root / "refund-check" / "references" / "extra.md"
            extra.write_text("This file was not in the approved manifest.\n", encoding="utf-8")
            listed_now = session.request(
                "resources/directory/read",
                {"uri": "skill://refund-check/references"},
            )["result"]["resources"]
            names = [item["name"] for item in listed_now]
            held_uris = {uri for uri, _digest in approval["resources"]}
            extra_uri = "skill://refund-check/references/extra.md"
            log(
                "directory/read after add "
                + ",".join(names)
                + f" extra_in_held={str(extra_uri in held_uris).lower()} surfaced=false"
            )
            require(names == ["extra.md", "policy.md"], "new child listed")
            require(extra_uri not in held_uris, "new child must stay outside the held set")

            policy_path = root / "refund-check" / "references" / "policy.md"
            policy_path.write_bytes(policy_path.read_bytes() + b"Tampered.\n")
            tampered = session.request("resources/read", {"uri": policy_uri})["result"]["contents"][0]["text"]
            tampered_bytes = tampered.encode("utf-8")
            tampered_digest = digest_of(tampered_bytes)
            mismatch = tampered_digest != policy_meta["digest"] or len(tampered_bytes) != policy_meta["size"]
            log(
                "resources/read policy.md after tamper "
                f"bytes={len(tampered_bytes)} digest={tampered_digest} "
                f"held={policy_meta['digest']} mismatch={str(mismatch).lower()} discarded=true"
            )
            require(mismatch, "tamper must change the digest or the size")
            require("Tampered." not in policy_body, "held body must stay the pre-tamper text")

            refreshed = session.request(
                "skills/get", {"uri": "skill://refund-check/SKILL.md"}
            )["result"]["skill"]
            refreshed_set = [(item["uri"], item["digest"]) for item in refreshed["resources"]]
            revoked = refreshed_set != approval["resources"]
            log(
                "skills/get after change "
                f"files={len(refreshed_set)} approval_revoked={str(revoked).lower()}"
            )
            require(revoked, "changed resources set must revoke approval")
            require(extra_uri in {uri for uri, _digest in refreshed_set}, "refreshed manifest includes extra.md")

            still = session.request(
                "tools/call",
                {"name": "check_refund", "arguments": {"amount": 500}},
            )["result"]["content"][0]["text"]
            log(f"tools/call check_refund amount=500 after tamper text={still}")
            require(still.startswith("refused:"), "tool cap survives a skill edit")
        finally:
            if proc.stdin:
                proc.stdin.close()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            err = proc.stderr.read().decode() if proc.stderr else ""
            if proc.returncode not in (0, None) and proc.returncode != -15:
                log(f"server_exit={proc.returncode}")
                if err.strip():
                    log(err.strip())

    sys.stdout.write("\n".join(lines) + "\n")


def session_text(lines: list[str]) -> str:
    return "\n".join(lines)


if __name__ == "__main__":
    main()
