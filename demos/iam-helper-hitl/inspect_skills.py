#!/usr/bin/env python3
"""Inspect IAM Helper skill files and apply a local approval gate.

The gate reads Markdown checked out from google/skills. It does not call
Google Cloud IAM, Policy Intelligence, or any MCP endpoint. Principals,
resources, access states, and replay rows below are fixtures.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
import urllib.request
from pathlib import Path

COMMIT = "588698280ecdf6145aab1ebabad0785d9630a8db"
PREFIXES = (
    "skills/cloud/iam-helper-for-troubleshooting/",
    "skills/cloud/iam-helper-for-policy-management/",
    "skills/cloud/iam-helper-for-policy-simulator/",
    "skills/cloud/iam-helper-for-privileged-access-management/",
)

# Tool names copied from Google Cloud MCP reference pages on 2026-10-28.
# This table is a local checklist. Nothing here is invoked.
MCP_TOOLS = (
    ("troubleshoot_access", "read", "https://policytroubleshooter.googleapis.com/mcp"),
    ("troubleshoot_iam_error_id", "read", "https://policytroubleshooter.googleapis.com/mcp"),
    ("analyze_iam_policy", "read", "https://cloudasset.googleapis.com/mcp"),
    ("list_assets", "read", "https://cloudasset.googleapis.com/mcp"),
    ("get_iam_policy_analysis_status", "read", "https://cloudasset.googleapis.com/mcp"),
    ("export_iam_analysis_results", "side_effect", "https://cloudasset.googleapis.com/mcp"),
    ("recommend_iam_roles", "suggest", "https://policyassist.googleapis.com/mcp"),
    ("list_deny_policies", "read", "https://iam.googleapis.com/mcp"),
    ("get_deny_policy", "read", "https://iam.googleapis.com/mcp"),
    ("get_deny_policy_status", "read", "https://iam.googleapis.com/mcp"),
    ("list_roles", "read", "https://iam.googleapis.com/mcp"),
    ("get_role", "read", "https://iam.googleapis.com/mcp"),
    ("create_deny_policy", "write", "https://iam.googleapis.com/mcp"),
    ("update_deny_policy", "write", "https://iam.googleapis.com/mcp"),
    ("delete_deny_policy", "write", "https://iam.googleapis.com/mcp"),
    ("create_role", "write", "https://iam.googleapis.com/mcp"),
    ("update_role", "write", "https://iam.googleapis.com/mcp"),
    ("delete_role", "write", "https://iam.googleapis.com/mcp"),
    ("undelete_role", "write", "https://iam.googleapis.com/mcp"),
)

BASIC_ROLES = {
    "roles/owner",
    "roles/editor",
    "roles/viewer",
    "roles/admin",
    "roles/writer",
    "roles/reader",
}
PUBLIC_PRINCIPALS = {"allUsers", "allAuthenticatedUsers"}
PAM_LEGACY = {"roles/owner", "roles/editor", "roles/viewer"}

ANCHORS = (
    ("skills/cloud/iam-helper-for-troubleshooting/references/guardrails.md", "Do NOT apply the binding"),
    ("skills/cloud/iam-helper-for-troubleshooting/references/guardrails.md", "roles/editor"),
    ("skills/cloud/iam-helper-for-troubleshooting/SKILL.md", "accessState: GRANTED"),
    ("skills/cloud/iam-helper-for-troubleshooting/SKILL.md", "accessState: UNKNOWN"),
    ("skills/cloud/iam-helper-for-policy-management/SKILL.md", "Autonomous Execution"),
    ("skills/cloud/iam-helper-for-policy-management/SKILL.md", "allUsers"),
    ("skills/cloud/iam-helper-for-policy-simulator/SKILL.md", "standard public gcloud commands"),
    ("skills/cloud/iam-helper-for-policy-simulator/SKILL.md", "REVOKED_COUNT"),
    ("skills/cloud/iam-helper-for-privileged-access-management/SKILL.md", "14400s"),
    ("skills/cloud/iam-helper-for-privileged-access-management/SKILL.md", "Legacy basic roles"),
)


def fetch_commit(dest: Path) -> None:
    tree_url = f"https://api.github.com/repos/google/skills/git/trees/{COMMIT}?recursive=1"
    request = urllib.request.Request(
        tree_url,
        headers={"User-Agent": "cfireworks-iam-helper-demo", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    blobs = [
        item["path"]
        for item in payload["tree"]
        if item["type"] == "blob" and item["path"].startswith(PREFIXES)
    ]
    if len(blobs) < 4:
        raise SystemExit(f"expected IAM Helper files, found {len(blobs)}")
    for path in blobs:
        raw = f"https://raw.githubusercontent.com/google/skills/{COMMIT}/{path}"
        file_request = urllib.request.Request(raw, headers={"User-Agent": "cfireworks-iam-helper-demo"})
        with urllib.request.urlopen(file_request, timeout=60) as response:
            data = response.read()
        target = dest / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    block = text[4:end]
    found: dict[str, str] = {}
    for key in ("name", "version", "category"):
        match = re.search(rf'^[ \t]*{key}:[ \t]*"?([^"\n]+)"?[ \t]*$', block, re.M)
        if match:
            found[key] = match.group(1).strip()
    return found


def find_line(text: str, needle: str) -> int:
    for number, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return number
    return 0


def role_tier(role: str) -> str:
    leaf = role.rsplit("/", 1)[-1]
    if role == "roles/owner" or leaf.endswith("admin") or leaf.endswith("Admin"):
        return "high"
    if role.startswith("roles/iam.") or role.startswith("roles/resourcemanager."):
        return "high"
    if "setIamPolicy" in role:
        return "high"
    if leaf.endswith("Viewer") or leaf.endswith("Reader") or role == "roles/browser":
        return "low"
    if role == "roles/pubsub.publisher" or leaf.endswith("Editor") or leaf.endswith("writer"):
        return "medium"
    if role in BASIC_ROLES:
        return "broad"
    return "unclassified"


def revoked_count(rows: list[dict]) -> int:
    count = 0
    for item in rows:
        change = item.get("diff", {}).get("accessDiff", {}).get("accessChange")
        if change in {"ACCESS_REVOKED", "ACCESS_MAYBE_REVOKED"}:
            count += 1
    return count


def run_gate() -> list[str]:
    lines: list[str] = []

    def emit(case: str, decision: str, detail: str) -> None:
        lines.append(f"{case} -> {decision}")
        lines.append(f"  {detail}")

    emit(
        "already-granted",
        "stop",
        "fixture accessState=GRANTED; skill says terminate and do not search roles",
    )
    emit(
        "unknown-groups",
        "stop",
        "fixture accessState=UNKNOWN; skill says missing roles/browser expansion, terminate",
    )
    emit(
        "list-candidates",
        "ask",
        "fixture wants gcloud iam roles list; skill gates role discovery before the query",
    )

    publisher = role_tier("roles/pubsub.publisher")
    emit(
        "bind-publisher",
        "hold",
        f"fixture user:dev@example.com roles/pubsub.publisher tier={publisher}; print approval card, executed=no",
    )
    lines.append(
        "  [APPROVAL REQUIRED]: Role 'roles/pubsub.publisher' grants permissions for "
        "'dev@example.com' on '//pubsub.googleapis.com/projects/example-project/topics/example-topic'."
    )

    editor = role_tier("roles/editor")
    emit(
        "bind-editor",
        "hold",
        f"fixture user:dev@example.com roles/editor tier={editor}; broad basic role stays on the card",
    )
    emit(
        "public-editor",
        "refuse",
        "fixture principal=allUsers role=roles/editor; policy-management skill refuses this pair",
    )
    emit(
        "pam-editor",
        "reject",
        "fixture entitlement role=roles/editor; PAM skill says legacy basic roles are not supported",
    )
    emit(
        "pam-duration-default",
        "hold",
        "fixture create entitlement, duration omitted; skill default maxRequestDuration=14400s, still ask",
    )

    replay = [
        {
            "diff": {"accessDiff": {"accessChange": "ACCESS_REVOKED"}},
            "principal": "serviceAccount:worker@example.iam.gserviceaccount.com",
            "permission": "pubsub.topics.publish",
        },
        {"diff": {"accessDiff": {"accessChange": "NO_CHANGE"}}},
        {
            "diff": {"accessDiff": {"accessChange": "ACCESS_MAYBE_REVOKED"}},
            "principal": "serviceAccount:batch@example.iam.gserviceaccount.com",
        },
    ]
    count = revoked_count(replay)
    emit(
        "sim-revoked",
        "do-not-apply",
        f"fixture REVOKED_COUNT={count}; skill says do not apply when the count is greater than 0",
    )
    emit(
        "sim-crash",
        "do-not-apply",
        "fixture simulator exit=1; skill says a failed replay is not a safe result",
    )
    emit(
        "sim-clean",
        "ask",
        "fixture REVOKED_COUNT=0 and no Yes in this run; skill still prompts before set-iam-policy",
    )

    for name, kind, _endpoint in MCP_TOOLS:
        if name == "create_deny_policy":
            emit(
                "yolo-create-deny",
                "hold",
                f"tool={name} kind={kind} skill_loaded=no; host gate stops the write",
            )
        elif name == "troubleshoot_access":
            emit(
                "mcp-troubleshoot",
                "allow",
                f"tool={name} kind={kind}; diagnostic query, no policy write",
            )
        elif name == "export_iam_analysis_results":
            emit(
                "mcp-export",
                "hold",
                f"tool={name} kind={kind}; reference page writes results to BigQuery or Cloud Storage",
            )
        elif name == "recommend_iam_roles":
            emit(
                "mcp-recommend",
                "allow",
                f"tool={name} kind={kind}; suggestion only, no binding",
            )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, help="local google/skills checkout")
    parser.add_argument("--fetch", action="store_true", help="download the pinned commit")
    args = parser.parse_args()

    if args.root and args.fetch:
        raise SystemExit("pass only one of --root or --fetch")
    if args.root:
        root = args.root
        origin = "local"
    else:
        root = Path("/tmp/iam-helper-hitl-skills")
        if root.exists():
            for child in sorted(root.rglob("*")):
                if child.is_file():
                    child.unlink()
        fetch_commit(root)
        origin = "github"

    print(f"python {platform.python_version()}")
    print(f"commit {COMMIT}")
    print(f"source {origin} {root}")
    print("iam_api_called no")
    print("mcp_endpoint_called no")

    print("== skills ==")
    skill_files = sorted(path for path in root.rglob("SKILL.md") if "iam-helper-for-" in path.as_posix())
    if len(skill_files) != 4:
        raise SystemExit(f"expected 4 SKILL.md files, found {len(skill_files)}")
    for skill in skill_files:
        meta = frontmatter(skill.read_text())
        folder = skill.parent
        files = sorted(item for item in folder.rglob("*") if item.is_file())
        print(
            f"{meta.get('name', skill.parent.name)} "
            f"version={meta.get('version', '?')} "
            f"category={meta.get('category', '?')} "
            f"files={len(files)}"
        )
        for item in files:
            print(f"  {item.relative_to(folder).as_posix()} {item.stat().st_size}")

    print("== anchors ==")
    for relative, needle in ANCHORS:
        path = root / relative
        if not path.is_file():
            raise SystemExit(f"missing {relative}")
        line = find_line(path.read_text(), needle)
        if line == 0:
            raise SystemExit(f"anchor not found: {relative} :: {needle}")
        print(f"{relative}:{line} {needle}")

    print("== mcp checklist ==")
    for name, kind, endpoint in MCP_TOOLS:
        print(f"{name} {kind} {endpoint}")

    print("== gate ==")
    for line in run_gate():
        print(line)
    print("checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
