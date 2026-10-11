#!/usr/bin/env python3
"""Resolve a Copilot-shaped local sandbox policy. This is not Copilot.

The rules below are the ones checked against GitHub's docs on 2026-10-11.
Nothing in this process starts a sandbox, calls MXC, or runs /sandbox policy.

Filesystem composition follows Copilot CLI's documented builder:

- deny by default unless a path is granted
- Include working directory (default on) grants the working directory read/write
- in a Git repository that same switch also grants .git read/write, and grants
  read access to the rest of the repository above the working directory
- turning the switch off suppresses those automatic grants
- extra read/write, read-only, and deny paths come from the request
- when read-only and read/write overlap, the longer path wins
- a deny on that winning path beats a grant of the same length
- a longer deny beats a shorter grant

The app docs state the same deny exception: a more specific denied folder stays
denied when a broader parent is readable or writable. They do not give an
example of a shorter deny against a longer grant. This resolver lets the longer
path win in that case, and says so in the output.

Network and credentials are independent booleans, the shape shared by the
Copilot app project settings and the CLI. Enterprise managed settings combine
in the restrictive direction: denied paths add up, user grants outside the
managed grant prefixes are dropped, a required sandbox stays on, and a managed
floor can force a boolean off. A boolean the user already turned off stays
off. Managed settings are not applied as a way to add access.

The launch section is a decision table copied from the docs, not an operating
system. An unsupported denied-path capability fails the shell closed. A host
with no sandbox support and only a user preference turns sandboxing off for
that session. failIfUnavailable together with a managed enable blocks the
session instead.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass


READ_WRITE = "read_write"
READ_ONLY = "read_only"
DENY = "deny"


@dataclass(frozen=True)
class Rule:
    path: str
    access: str
    source: str


@dataclass(frozen=True)
class Requested:
    sandbox_enabled: bool
    include_working_directory: bool
    cwd: str
    repo_root: str | None
    read_write: tuple[str, ...]
    read_only: tuple[str, ...]
    deny: tuple[str, ...]
    outbound_internet: bool
    local_network: bool
    git_credentials: bool
    gh_credentials: bool


@dataclass(frozen=True)
class ManagedFloor:
    require_sandbox: bool
    allow_bypass: bool
    lock_include_working_directory_off: bool
    grant_prefixes: tuple[str, ...]
    deny_paths: tuple[str, ...]
    force_outbound_off: bool
    force_local_network_off: bool
    force_git_credentials_off: bool
    force_gh_credentials_off: bool


@dataclass(frozen=True)
class Effective:
    sandbox_enabled: bool
    include_working_directory: bool
    outbound_internet: bool
    local_network: bool
    git_credentials: bool
    gh_credentials: bool
    allow_bypass: bool
    rules: tuple[Rule, ...]
    dropped_grants: tuple[str, ...]
    notes: tuple[str, ...]


def norm(path: str) -> str:
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    if not path.startswith("/"):
        raise SystemExit(f"FAIL relative path {path}")
    return path


def under(path: str, root: str) -> bool:
    path, root = norm(path), norm(root)
    return path == root or path.startswith(root + "/")


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def tighten_bool(requested: bool, force_off: bool) -> bool:
    if force_off:
        return False
    return requested


def compose(req: Requested, managed: ManagedFloor) -> Effective:
    notes: list[str] = []
    include = req.include_working_directory
    if managed.lock_include_working_directory_off:
        if include:
            notes.append("include_working_directory locked off by managed floor")
        include = False

    sandbox_enabled = req.sandbox_enabled or managed.require_sandbox
    if managed.require_sandbox and not req.sandbox_enabled:
        notes.append("sandbox required by managed floor; user off ignored")
    if managed.require_sandbox:
        notes.append("sandbox required stays on")

    dropped: list[str] = []
    rules: list[Rule] = []

    def keep_grant(path: str) -> bool:
        if any(under(path, prefix) for prefix in managed.grant_prefixes):
            return True
        dropped.append(norm(path))
        return False

    for path in req.read_write:
        if keep_grant(path):
            rules.append(Rule(norm(path), READ_WRITE, "user"))
    for path in req.read_only:
        if keep_grant(path):
            rules.append(Rule(norm(path), READ_ONLY, "user"))
    for path in req.deny:
        rules.append(Rule(norm(path), DENY, "user"))
    for path in managed.deny_paths:
        rules.append(Rule(norm(path), DENY, "managed"))
        notes.append(f"managed deny added {norm(path)}")

    if include:
        rules.append(Rule(norm(req.cwd), READ_WRITE, "automatic"))
        notes.append(f"automatic read_write {norm(req.cwd)}")
        if req.repo_root is not None:
            root = norm(req.repo_root)
            require(under(req.cwd, root), "cwd is outside repo_root")
            rules.append(Rule(root + "/.git", READ_WRITE, "automatic"))
            rules.append(Rule(root, READ_ONLY, "automatic"))
            notes.append(f"automatic read_write {root}/.git")
            notes.append(f"automatic read_only {root}")
    else:
        notes.append("automatic working-directory and git grants suppressed")

    outbound = tighten_bool(req.outbound_internet, managed.force_outbound_off)
    local_network = tighten_bool(req.local_network, managed.force_local_network_off)
    git_credentials = tighten_bool(req.git_credentials, managed.force_git_credentials_off)
    gh_credentials = tighten_bool(req.gh_credentials, managed.force_gh_credentials_off)
    if req.outbound_internet and not outbound:
        notes.append("outbound tightened off")
    if req.local_network and not local_network:
        notes.append("local_network tightened off")
    if req.git_credentials and not git_credentials:
        notes.append("git_credentials tightened off")
    if req.gh_credentials and not gh_credentials:
        notes.append("gh_credentials tightened off")
    if not req.local_network:
        notes.append("user local_network off stays off")

    ordered = tuple(sorted(rules, key=lambda r: (r.path, r.access, r.source)))
    return Effective(
        sandbox_enabled=sandbox_enabled,
        include_working_directory=include,
        outbound_internet=outbound,
        local_network=local_network,
        git_credentials=git_credentials,
        gh_credentials=gh_credentials,
        allow_bypass=managed.allow_bypass,
        rules=ordered,
        dropped_grants=tuple(dropped),
        notes=tuple(notes),
    )


def winner(path: str, rules: tuple[Rule, ...]) -> Rule | None:
    matches = [rule for rule in rules if under(path, rule.path)]
    if not matches:
        return None
    longest = max(len(rule.path) for rule in matches)
    top = [rule for rule in matches if len(rule.path) == longest]
    denies = [rule for rule in top if rule.access == DENY]
    if denies:
        return sorted(denies, key=lambda r: r.source)[0]
    return sorted(top, key=lambda r: (r.access, r.source))[0]


def path_decision(op: str, path: str, rules: tuple[Rule, ...]) -> tuple[str, str]:
    rule = winner(path, rules)
    if rule is None:
        return "DENY", "deny-by-default"
    if op == "read" and rule.access in (READ_WRITE, READ_ONLY):
        return "ALLOW", f"{rule.source} {rule.path} {rule.access}"
    if op == "write" and rule.access == READ_WRITE:
        return "ALLOW", f"{rule.source} {rule.path} {rule.access}"
    return "DENY", f"{rule.source} {rule.path} {rule.access}"


def digest(eff: Effective) -> str:
    payload = {
        "sandbox_enabled": eff.sandbox_enabled,
        "include_working_directory": eff.include_working_directory,
        "outbound_internet": eff.outbound_internet,
        "local_network": eff.local_network,
        "git_credentials": eff.git_credentials,
        "gh_credentials": eff.gh_credentials,
        "allow_bypass": eff.allow_bypass,
        "dropped_grants": list(eff.dropped_grants),
        "rules": [
            {"path": r.path, "access": r.access, "source": r.source} for r in eff.rules
        ],
    }
    raw = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def fmt_bool(value: bool) -> str:
    return "on" if value else "off"


def print_request(req: Requested) -> None:
    print(f"sandbox_enabled {fmt_bool(req.sandbox_enabled)}")
    print(f"include_working_directory {fmt_bool(req.include_working_directory)}")
    print(f"cwd {req.cwd}")
    print(f"repo_root {req.repo_root}")
    print("read_write " + ",".join(req.read_write))
    print("read_only " + ",".join(req.read_only))
    print("deny " + ",".join(req.deny))
    print(f"outbound_internet {fmt_bool(req.outbound_internet)}")
    print(f"local_network {fmt_bool(req.local_network)}")
    print(f"git_credentials {fmt_bool(req.git_credentials)}")
    print(f"gh_credentials {fmt_bool(req.gh_credentials)}")


def print_managed(managed: ManagedFloor) -> None:
    print(f"require_sandbox {fmt_bool(managed.require_sandbox)}")
    print(f"allow_bypass {fmt_bool(managed.allow_bypass)}")
    print(
        "lock_include_working_directory_off "
        f"{fmt_bool(managed.lock_include_working_directory_off)}"
    )
    print("grant_prefixes " + ",".join(managed.grant_prefixes))
    print("deny_paths " + ",".join(managed.deny_paths))
    print(f"force_outbound_off {fmt_bool(managed.force_outbound_off)}")
    print(f"force_local_network_off {fmt_bool(managed.force_local_network_off)}")
    print(f"force_git_credentials_off {fmt_bool(managed.force_git_credentials_off)}")
    print(f"force_gh_credentials_off {fmt_bool(managed.force_gh_credentials_off)}")


def print_effective(eff: Effective) -> None:
    print(f"sandbox_enabled {fmt_bool(eff.sandbox_enabled)}")
    print(f"include_working_directory {fmt_bool(eff.include_working_directory)}")
    print(f"outbound_internet {fmt_bool(eff.outbound_internet)}")
    print(f"local_network {fmt_bool(eff.local_network)}")
    print(f"git_credentials {fmt_bool(eff.git_credentials)}")
    print(f"gh_credentials {fmt_bool(eff.gh_credentials)}")
    print(f"allow_bypass {fmt_bool(eff.allow_bypass)}")
    if eff.dropped_grants:
        print("dropped_grants " + ",".join(eff.dropped_grants))
    else:
        print("dropped_grants -")
    for rule in eff.rules:
        print(f"rule {rule.access} {rule.path} source={rule.source}")
    for note in eff.notes:
        print(f"note {note}")
    print(f"effective_sha256_12 {digest(eff)}")


def check_commands(eff: Effective) -> None:
    checks = [
        ("read", "/work/app/src/main.py", "ALLOW"),
        ("write", "/work/app/src/main.py", "ALLOW"),
        ("read", "/work/README.md", "ALLOW"),
        ("write", "/work/README.md", "DENY"),
        ("read", "/work/.git/HEAD", "ALLOW"),
        ("write", "/work/.git/index", "ALLOW"),
        ("read", "/work/app/secrets/token", "DENY"),
        ("read", "/work/.env", "DENY"),
        ("read", "/home/dev/.aws/credentials", "DENY"),
    ]
    for op, path, expect in checks:
        decision, why = path_decision(op, path, eff.rules)
        print(f"{decision} {op} {path} via {why}")
        require(decision == expect, f"{op} {path} -> {decision}, expected {expect}")

    print("DENY network outbound host=registry.npmjs.org via outbound off")
    require(not eff.outbound_internet, "outbound should be off")
    print("DENY network local host=127.0.0.1 via local_network off")
    require(not eff.local_network, "local network should be off")

    push = []
    if not eff.git_credentials:
        push.append("git_credentials off")
    if not eff.outbound_internet:
        push.append("outbound off")
    print("DENY git push via " + " + ".join(push))
    require(push == ["git_credentials off", "outbound off"], "git push reasons")

    gh = []
    if not eff.gh_credentials:
        gh.append("gh_credentials off")
    if not eff.outbound_internet:
        gh.append("outbound off")
    print("DENY gh pr create via " + " + ".join(gh))
    require(gh == ["outbound off"], "gh should fail only on outbound")
    require(eff.gh_credentials, "gh credential flag stays on")


def refuse_loosen_and_accept_tighten(req: Requested, managed: ManagedFloor, eff: Effective) -> None:
    loosened = Requested(
        sandbox_enabled=False,
        include_working_directory=req.include_working_directory,
        cwd=req.cwd,
        repo_root=req.repo_root,
        read_write=req.read_write + ("/tmp/outside-grant-ceiling",),
        read_only=req.read_only,
        deny=tuple(p for p in req.deny if p != "/work/app/secrets"),
        outbound_internet=True,
        local_network=True,
        git_credentials=True,
        gh_credentials=True,
    )
    again = compose(loosened, managed)
    print(
        "loosen_attempt sandbox off, outbound on, local_network on, "
        "git on, drop user deny, add /tmp/outside-grant-ceiling"
    )
    secrets_denied = any(
        r.path == "/work/app/secrets" and r.access == DENY for r in again.rules
    )
    env_denied = any(r.path == "/work/.env" and r.source == "managed" for r in again.rules)
    print(
        "loosen_result "
        f"sandbox {fmt_bool(again.sandbox_enabled)} "
        f"outbound {fmt_bool(again.outbound_internet)} "
        f"local_network {fmt_bool(again.local_network)} "
        f"git {fmt_bool(again.git_credentials)} "
        f"user_deny_secrets {fmt_bool(secrets_denied)} "
        f"managed_deny_env {fmt_bool(env_denied)} "
        f"dropped {'yes' if '/tmp/outside-grant-ceiling' in again.dropped_grants else 'no'}"
    )
    require(again.sandbox_enabled, "required sandbox was loosened")
    require(not again.outbound_internet, "outbound was loosened")
    require(again.local_network, "user turning local_network on is not a managed force-off")
    require(not again.git_credentials, "git credentials were loosened")
    require(
        any(r.path == "/work/app/secrets" and r.access == DENY for r in again.rules) is False,
        "dropping a user deny should be allowed; it is the user tightening less",
    )
    require("/tmp/outside-grant-ceiling" in again.dropped_grants, "grant ceiling missed")
    require(
        not any(r.path == "/work/app/secrets" and r.source == "user" for r in again.rules),
        "removed user deny came back",
    )
    # The managed deny on .env remains. The user may remove their own deny.
    require(any(r.path == "/work/.env" and r.source == "managed" for r in again.rules), "managed deny lost")

    tightened = compose(
        Requested(
            sandbox_enabled=req.sandbox_enabled,
            include_working_directory=req.include_working_directory,
            cwd=req.cwd,
            repo_root=req.repo_root,
            read_write=req.read_write,
            read_only=req.read_only,
            deny=req.deny,
            outbound_internet=req.outbound_internet,
            local_network=req.local_network,
            git_credentials=req.git_credentials,
            gh_credentials=False,
        ),
        managed,
    )
    print("tighten_attempt gh_credentials off")
    print(f"tighten_result gh {fmt_bool(tightened.gh_credentials)}")
    require(not tightened.gh_credentials, "user could not tighten gh")
    require(eff.gh_credentials, "main policy gh flag changed")

    print("session_opt_out allow_bypass=off -> refused saved_policy_unchanged")
    require(not eff.allow_bypass, "bypass should be off in this floor")
    require(eff.sandbox_enabled, "saved sandbox changed by a refused opt-out")


def launch_table(eff: Effective) -> None:
    """Print documented launch decisions. No process is spawned."""
    has_deny = any(rule.access == DENY for rule in eff.rules)
    require(has_deny, "scenario needs a deny rule to show unsupported-policy")
    would = path_decision("read", "/work/app/src/main.py", eff.rules)
    require(would[0] == "ALLOW", "sample command should be allowed by path policy")

    print("case denied_path_unsupported")
    print("mode simulated_documented_decision")
    print("host_supports_sandbox yes")
    print("can_enforce_denied_paths no")
    print("command read /work/app/src/main.py")
    print(f"path_policy {would[0]}")
    print("result error unsupported-policy")
    print("executed no")
    print("ran_unsandboxed no")

    print("case user_preference_unsupported_host")
    print("mode simulated_documented_decision")
    print("host_supports_sandbox no")
    print("fail_if_unavailable no")
    print("managed_require_sandbox no")
    print("result session_sandbox_off")
    print("commands_run_without_sandbox yes")
    print("saved_enabled_unchanged yes")
    print("sandbox_enable_on_this_host refused")

    print("case managed_fail_if_unavailable")
    print("mode simulated_documented_decision")
    print("host_supports_sandbox no")
    print("fail_if_unavailable yes")
    print("managed_require_sandbox yes")
    print("result block_model_and_tool_execution")
    print("executed no")
    print("ran_unsandboxed no")


def locked_off(req: Requested, managed: ManagedFloor) -> None:
    floor = ManagedFloor(
        require_sandbox=managed.require_sandbox,
        allow_bypass=managed.allow_bypass,
        lock_include_working_directory_off=True,
        grant_prefixes=managed.grant_prefixes,
        deny_paths=managed.deny_paths,
        force_outbound_off=managed.force_outbound_off,
        force_local_network_off=managed.force_local_network_off,
        force_git_credentials_off=managed.force_git_credentials_off,
        force_gh_credentials_off=managed.force_gh_credentials_off,
    )
    eff = compose(req, floor)
    print(f"include_working_directory {fmt_bool(eff.include_working_directory)}")
    decision, why = path_decision("read", "/work/.git/HEAD", eff.rules)
    print(f"{decision} read /work/.git/HEAD via {why}")
    require(decision == "DENY", "git grant survived a locked-off working directory")
    require(not any(rule.source == "automatic" for rule in eff.rules), "automatic grant remained")
    src, why_src = path_decision("read", "/work/app/src/main.py", eff.rules)
    print(f"{src} read /work/app/src/main.py via {why_src}")
    require(src == "DENY", "cwd stayed granted after the lock")


def main() -> None:
    print(f"python {platform.python_version()}")
    print("demo copilot-local-sandbox-policy")
    print("resolver_only yes")
    print("copilot_cli no")
    print("mxc_spawn no")
    print("os_sandbox no")

    req = Requested(
        sandbox_enabled=True,
        include_working_directory=True,
        cwd="/work/app",
        repo_root="/work",
        read_write=("/work/shared-notes",),
        read_only=("/opt/vendor-sdk", "/home/dev/.aws"),
        deny=("/work/app/secrets",),
        outbound_internet=True,
        local_network=False,
        git_credentials=True,
        gh_credentials=True,
    )
    managed = ManagedFloor(
        require_sandbox=True,
        allow_bypass=False,
        lock_include_working_directory_off=False,
        grant_prefixes=("/work", "/opt/vendor-sdk"),
        deny_paths=("/work/.env",),
        force_outbound_off=True,
        force_local_network_off=False,
        force_git_credentials_off=True,
        force_gh_credentials_off=False,
    )

    print("== requested ==")
    print_request(req)
    print("== managed floor ==")
    print_managed(managed)
    eff = compose(req, managed)
    print("== effective ==")
    print_effective(eff)
    print("overlap more_specific_path_wins deny_breaks_equal_length_tie")

    print("== commands ==")
    check_commands(eff)
    print("== cannot loosen ==")
    refuse_loosen_and_accept_tighten(req, managed, eff)
    print("== include locked off ==")
    locked_off(req, managed)
    print("== launch decisions ==")
    launch_table(eff)
    print("checks passed")


if __name__ == "__main__":
    main()
