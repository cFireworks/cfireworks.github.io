#!/usr/bin/env python3
"""Offline model of layered authorization for MCP tools.

This is not Safeguard's server. It does not open a socket, read credentials,
or call an API. Tool names in DEFAULT_READS are the six read-only tools the
tool-gating docs list as the new-workspace default. Everything else — allow
sets, confirmation, and the refusal line — is this script's decision model
for the blog post.

Vendor docs say Guard tool matchers may use glob wildcards. This script
compares exact tool names only, plus an agent pattern of ``*`` or one id.
"""

from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_READS = frozenset(
    {
        "safeguard_get_project",
        "safeguard_get_vulnerability",
        "safeguard_list_findings",
        "safeguard_list_products",
        "safeguard_list_projects",
        "safeguard_list_vulnerabilities",
    }
)
WRITE_SCAN = "safeguard_scan_repository"
WRITE_MERGE = "safeguard_merge_pull_request"
CATALOG = DEFAULT_READS | frozenset({WRITE_SCAN, WRITE_MERGE})

ORG_ALLOWS = {
    "platform": CATALOG,
    "interns": DEFAULT_READS,
    "security": DEFAULT_READS,
}
ROLE_ALLOWS = {
    "auditor": DEFAULT_READS,
    "maintainer": CATALOG,
}
AGENT_ALLOWS = {
    "triage-bot": DEFAULT_READS,
    "release-bot": CATALOG,
}


class ResolutionError(Exception):
    """Tool-enablement lookup could not finish."""


@dataclass
class Tenant:
    name: str
    enabled: frozenset[str]
    fail: bool = False
    history: list[frozenset[str]] = field(default_factory=list)

    def resolve(self) -> frozenset[str]:
        if self.fail:
            raise ResolutionError(self.name)
        return self.enabled


def enabled_tools(tenant: Tenant) -> frozenset[str]:
    """Same set for discovery and execution. Failure falls back to reads."""
    try:
        resolved = tenant.resolve()
    except ResolutionError:
        return DEFAULT_READS
    return resolved


def list_tools(tenant: Tenant) -> tuple[str, ...]:
    return tuple(sorted(enabled_tools(tenant)))


@dataclass(frozen=True)
class Principal:
    tenant: Tenant
    organization: str
    role: str
    agent: str
    org_allows: frozenset[str]
    role_allows: frozenset[str]
    agent_allows: frozenset[str]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    layer: str


def principal(tenant: Tenant, organization: str, role: str, agent: str) -> Principal:
    """Missing org, role, or agent config is an empty allow-set (fail closed)."""
    return Principal(
        tenant,
        organization,
        role,
        agent,
        ORG_ALLOWS.get(organization, frozenset()),
        ROLE_ALLOWS.get(role, frozenset()),
        AGENT_ALLOWS.get(agent, frozenset()),
    )


def authorize(who: Principal, tool: str) -> Decision:
    """First failing layer wins, so the refusal names that layer only."""
    if tool not in enabled_tools(who.tenant):
        return Decision(False, "tenant")
    if tool not in who.org_allows:
        return Decision(False, "organization")
    if tool not in who.role_allows:
        return Decision(False, "role")
    if tool not in who.agent_allows:
        return Decision(False, "agent")
    return Decision(True, "allow")


def widen(tenant: Tenant, tool: str, confirmed: bool) -> str:
    if tool in tenant.enabled:
        return "unchanged"
    if not confirmed:
        return "confirmation_required"
    tenant.history.append(tenant.enabled)
    tenant.enabled = tenant.enabled | frozenset((tool,))
    return "widened"


def undo(tenant: Tenant) -> str:
    if not tenant.history:
        return "empty"
    tenant.enabled = tenant.history.pop()
    return "undone"


@dataclass(frozen=True)
class GuardRule:
    priority: int
    tool: str
    agent: str
    action: str


def guard_action(rules: tuple[GuardRule, ...], tool: str, agent: str) -> str:
    """Highest priority first. No match monitors; it does not silently allow."""
    ordered = tuple(
        sorted(rules, key=lambda rule: (-rule.priority, rule.tool, rule.agent, rule.action))
    )
    for rule in ordered:
        if rule.tool != tool:
            continue
        if rule.agent not in ("*", agent):
            continue
        return rule.action
    return "monitor"


GUARD_RULES = (
    GuardRule(10, "safeguard_list_findings", "triage-bot", "deny"),
    GuardRule(1, "safeguard_list_findings", "*", "allow"),
)


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def joined(names: frozenset[str] | tuple[str, ...]) -> str:
    return ",".join(sorted(names))


def show_call(label: str, who: Principal, tool: str) -> Decision:
    decision = authorize(who, tool)
    print(
        f"{label} call tool={tool} org={who.organization} "
        f"role={who.role} agent={who.agent} layer={decision.layer}"
    )
    return decision


def assert_same_source(tenant: Tenant) -> None:
    advertised = set(list_tools(tenant))
    require(advertised == set(enabled_tools(tenant)), f"list/call split {tenant.name}")
    opened = Principal(
        tenant,
        "open",
        "open",
        "open",
        CATALOG,
        CATALOG,
        CATALOG,
    )
    for tool in sorted(CATALOG):
        decision = authorize(opened, tool)
        if tool in advertised:
            require(decision.allowed and decision.layer == "allow", f"listed {tool}")
        else:
            require((not decision.allowed) and decision.layer == "tenant", f"unlisted {tool}")
    print(
        f"same_source tenant={tenant.name} listed={len(advertised)} "
        f"unlisted_layer=tenant listed_layer=allow"
    )


def main() -> None:
    fresh = Tenant("fresh", DEFAULT_READS)
    legacy = Tenant("legacy", DEFAULT_READS | frozenset((WRITE_SCAN,)))
    broken = Tenant(
        "broken",
        DEFAULT_READS | frozenset((WRITE_SCAN, WRITE_MERGE)),
        fail=True,
    )

    print(f"catalog={joined(CATALOG)}")
    print(f"fresh list={joined(list_tools(fresh))}")
    fresh_reader = principal(fresh, "security", "maintainer", "triage-bot")
    read_ok = show_call("fresh", fresh_reader, "safeguard_list_findings")
    scan_blocked = show_call("fresh", fresh_reader, WRITE_SCAN)
    merge_blocked = show_call("fresh", fresh_reader, WRITE_MERGE)
    require(read_ok.layer == "allow", "fresh read")
    require(scan_blocked.layer == "tenant", "fresh scan")
    require(merge_blocked.layer == "tenant", "fresh merge")
    require(WRITE_SCAN in fresh_reader.role_allows, "role would have allowed scan")
    require(WRITE_SCAN not in list_tools(fresh), "scan not advertised")

    assert_same_source(fresh)
    assert_same_source(legacy)
    assert_same_source(broken)

    print(f"legacy list_has_scan={WRITE_SCAN in list_tools(legacy)} list_count={len(list_tools(legacy))}")
    org_no = show_call(
        "legacy",
        principal(legacy, "interns", "maintainer", "release-bot"),
        WRITE_SCAN,
    )
    role_no = show_call(
        "legacy",
        principal(legacy, "platform", "auditor", "release-bot"),
        WRITE_SCAN,
    )
    agent_no = show_call(
        "legacy",
        principal(legacy, "platform", "maintainer", "triage-bot"),
        WRITE_SCAN,
    )
    agent_yes = show_call(
        "legacy",
        principal(legacy, "platform", "maintainer", "release-bot"),
        WRITE_SCAN,
    )
    stranger = show_call(
        "legacy",
        principal(legacy, "platform", "maintainer", "stranger"),
        WRITE_SCAN,
    )
    require(org_no.layer == "organization", "org")
    require(role_no.layer == "role", "role")
    require(agent_no.layer == "agent", "agent")
    require(agent_yes.allowed and agent_yes.layer == "allow", "release")
    require(stranger.layer == "agent", "unknown agent")
    require(WRITE_SCAN in list_tools(legacy), "legacy still advertises scan")

    visible = set(list_tools(broken))
    broken_call = show_call(
        "resolve",
        principal(broken, "platform", "maintainer", "release-bot"),
        WRITE_SCAN,
    )
    print(
        "resolve fallback=default_reads "
        f"payload_has_scan={WRITE_SCAN in broken.enabled} "
        f"visible={WRITE_SCAN in visible} call_layer={broken_call.layer}"
    )
    require(visible == set(DEFAULT_READS), "fallback set")
    require(WRITE_SCAN in broken.enabled and WRITE_SCAN not in visible, "no leak")
    require(broken_call.layer == "tenant", "fallback call")

    held = show_call(
        "widen",
        principal(fresh, "platform", "maintainer", "release-bot"),
        WRITE_MERGE,
    )
    refused = widen(fresh, WRITE_MERGE, confirmed=False)
    print(
        f"widen confirmed=false result={refused} "
        f"listed={WRITE_MERGE in list_tools(fresh)} history={len(fresh.history)}"
    )
    require(held.layer == "tenant", "merge still off")
    require(refused == "confirmation_required", "confirm")
    require(WRITE_MERGE not in list_tools(fresh) and len(fresh.history) == 0, "no silent widen")

    opened = widen(fresh, WRITE_MERGE, confirmed=True)
    print(
        f"widen confirmed=true result={opened} "
        f"listed={WRITE_MERGE in list_tools(fresh)} history={len(fresh.history)}"
    )
    triage_after = show_call(
        "widen",
        principal(fresh, "platform", "maintainer", "triage-bot"),
        WRITE_MERGE,
    )
    release_after = show_call(
        "widen",
        principal(fresh, "platform", "maintainer", "release-bot"),
        WRITE_MERGE,
    )
    require(opened == "widened" and WRITE_MERGE in list_tools(fresh), "listed after widen")
    require(triage_after.layer == "agent", "triage still blocked")
    require(release_after.layer == "allow", "release can merge")

    undone = undo(fresh)
    after_undo = show_call(
        "undo",
        principal(fresh, "platform", "maintainer", "release-bot"),
        WRITE_MERGE,
    )
    print(f"undo result={undone} listed={WRITE_MERGE in list_tools(fresh)} history={len(fresh.history)}")
    require(undone == "undone" and after_undo.layer == "tenant", "undo restores")
    require(WRITE_MERGE not in list_tools(fresh) and len(fresh.history) == 0, "history cleared")

    identity = authorize(principal(fresh, "security", "maintainer", "triage-bot"), "safeguard_list_findings")
    triage_guard = guard_action(GUARD_RULES, "safeguard_list_findings", "triage-bot")
    release_guard = guard_action(GUARD_RULES, "safeguard_list_findings", "release-bot")
    monitor = guard_action(GUARD_RULES, "safeguard_get_project", "triage-bot")
    print(
        "guard tool=safeguard_list_findings agent=triage-bot "
        f"identity={identity.layer} action={triage_guard}"
    )
    print(
        "guard tool=safeguard_list_findings agent=release-bot "
        f"identity=allow action={release_guard}"
    )
    print(
        "guard tool=safeguard_get_project agent=triage-bot "
        f"identity=allow action={monitor}"
    )
    require(identity.layer == "allow" and triage_guard == "deny", "guard independent deny")
    require("safeguard_list_findings" in list_tools(fresh), "deny does not unlist")
    require(release_guard == "allow", "lower priority allow")
    require(monitor == "monitor", "no match monitors")

    gated = Tenant("gated-off", DEFAULT_READS - frozenset(("safeguard_list_findings",)))
    still = guard_action(GUARD_RULES, "safeguard_list_findings", "triage-bot")
    print(
        f"guard rules_before={len(GUARD_RULES)} rules_after_gating_off={len(GUARD_RULES)} "
        f"listed_after_off={'safeguard_list_findings' in list_tools(gated)} "
        f"action_still={still}"
    )
    require("safeguard_list_findings" not in list_tools(gated), "flag off hides tool")
    require(still == "deny" and len(GUARD_RULES) == 2, "flag does not edit guard")

    print("checks passed")


if __name__ == "__main__":
    main()
