#!/usr/bin/env python3
"""Simulator for Harbor sbx phase-split network policy.

This process does not call harbor, sbx, Docker, or the network. It is not a
MicroVM, not Compose, and not Dogwood. The rules below are copied from
harbor-framework/harbor main at 2de4605b, read on 2026-10-16:

- src/harbor/trial/trial.py: agent.setup() is outside the phase switch.
  agent.run() uses _phase_network_policy. A phase equal to the baseline does
  not switch. A different phase needs dynamic_network_policy.
- src/harbor/environments/base.py: an unsupported mode or allowlist entry type
  raises ValueError and tells the provider to reject the task.
- src/harbor/environments/sbx/environment.py: cloud gets allowlist, exact
  hostnames, and dynamic policy. Local gets disable_internet only, plus
  docker_compose on both targets. Wildcard, IP, and CIDR flags stay false.
- src/harbor/environments/sbx/local.py: apply_network_policy accepts only
  no-network, then argv is `sbx policy deny network --sandbox <name> **`.
- src/harbor/environments/sbx/compose.py: a non-public baseline pulls image-only
  services before apply_network_policy, then builds Dockerfiles under it.
- src/harbor/environments/sbx/remote.py: policy_document maps public to
  allow-all, no-network to deny-all, and allowlist to deny-all plus
  allowNetworks. The mapper forwards whatever hosts it is given.
- src/harbor/environments/sbx/cloud/sandboxes.py: the module docstring says an
  acknowledged policy-store write is not an enforcement barrier.

Hostname matching here is exact after strip, lower, and a trailing-dot strip.
That normalization is Harbor's for allowlist entries. It is not a reading of
the cloud dataplane. A write under tests/ or a score file is network=skip:
the gate never sees it.
"""

from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TASKS = ROOT / "tasks"
SHA = "2de4605b"

CLOUD_CAPS = frozenset(
    {
        "disable_internet",
        "network_allowlist",
        "network_allowlist_hostnames",
        "dynamic_network_policy",
        "docker_compose",
    }
)
LOCAL_CAPS = frozenset({"disable_internet", "docker_compose"})

ENTRY_CAPS = (
    ("hostname", "hostnames", "network_allowlist_hostnames"),
    ("wildcard", "wildcard hostnames", "network_allowlist_wildcard_hostnames"),
    ("ipv4", "IPv4 addresses", "network_allowlist_ipv4_addresses"),
    ("ipv6", "IPv6 addresses", "network_allowlist_ipv6_addresses"),
    ("ipv4_cidr", "IPv4 CIDR ranges", "network_allowlist_ipv4_cidrs"),
    ("ipv6_cidr", "IPv6 CIDR ranges", "network_allowlist_ipv6_cidrs"),
)

REJECT_TAIL = (
    "Environment providers must enforce the requested network policy or reject the task."
)

CHECKS = 0


@dataclass(frozen=True)
class Policy:
    mode: str
    hosts: tuple[str, ...]


@dataclass(frozen=True)
class Task:
    environment: Policy
    agent: Policy | None
    verifier: Policy | None


def require(cond: bool, message: str) -> None:
    global CHECKS
    if not cond:
        raise SystemExit(f"FAIL {message}")
    CHECKS += 1


def normalize_host(host: str) -> str:
    return host.strip().lower().rstrip(".")


def classify(entry: str) -> str:
    if entry.startswith("*."):
        return "wildcard"
    if "/" in entry:
        network = ip_network(entry, strict=True)
        return "ipv4_cidr" if network.version == 4 else "ipv6_cidr"
    try:
        address = ip_address(entry)
    except ValueError:
        return "hostname"
    return "ipv4" if address.version == 4 else "ipv6"


def caps_for(target: str) -> frozenset[str]:
    if target == "cloud":
        return CLOUD_CAPS
    if target == "local":
        return LOCAL_CAPS
    raise SystemExit(f"FAIL unknown target {target}")


def support_error(caps: frozenset[str], policy: Policy) -> str | None:
    if policy.mode == "no-network" and "disable_internet" not in caps:
        return f"network_mode='no-network' is not supported by sbx environment. {REJECT_TAIL}"
    if policy.mode != "allowlist":
        return None
    if "network_allowlist" not in caps:
        return f"network_mode='allowlist' is not supported by sbx environment. {REJECT_TAIL}"
    present = {classify(host) for host in policy.hosts}
    for kind, label, cap in ENTRY_CAPS:
        if kind in present and cap not in caps:
            return (
                f"network_mode='allowlist' with {label} is not supported by sbx "
                f"environment. {REJECT_TAIL}"
            )
    return None


def dynamic_error(phase: str) -> str:
    return (
        f"[agent] {phase} phase network policy differs from the agent environment "
        "baseline, but this environment cannot change network policy after start."
    )


def validate(target: str, task: Task) -> str | None:
    caps = caps_for(target)
    error = support_error(caps, task.environment)
    if error:
        return error
    overrides = (("agent", task.agent), ("verifier", task.verifier))
    for phase, policy in overrides:
        if policy is None or policy == task.environment:
            continue
        error = support_error(caps, policy)
        if error:
            return error
        if "dynamic_network_policy" not in caps:
            return dynamic_error(phase)
    return None


def parse_policy(section: dict) -> Policy:
    mode = section.get("network_mode")
    if mode not in {"public", "no-network", "allowlist"}:
        raise SystemExit(f"FAIL bad network_mode {mode!r}")
    hosts = section.get("allowed_hosts", [])
    if not isinstance(hosts, list) or not all(isinstance(item, str) for item in hosts):
        raise SystemExit("FAIL allowed_hosts must be a list of strings")
    return Policy(mode=mode, hosts=tuple(normalize_host(item) for item in hosts))


def load_task(name: str) -> Task:
    data = tomllib.loads((TASKS / f"{name}.toml").read_text(encoding="utf-8"))
    if "environment" not in data:
        raise SystemExit(f"FAIL {name} missing [environment]")
    return Task(
        environment=parse_policy(data["environment"]),
        agent=parse_policy(data["agent"]) if "agent" in data else None,
        verifier=parse_policy(data["verifier"]) if "verifier" in data else None,
    )


def decide(policy: Policy, host: str) -> str:
    if policy.mode == "public":
        return "allow"
    if policy.mode == "no-network":
        return "deny"
    if normalize_host(host) in policy.hosts:
        return "allow"
    return "deny"


def active(task: Task, phase: str) -> tuple[str, Policy]:
    if phase in {"dockerfile_build", "agent_setup"}:
        return "environment", task.environment
    if phase == "agent_run":
        if task.agent is not None:
            return "agent", task.agent
        return "environment", task.environment
    if phase == "verifier":
        if task.verifier is not None:
            return "verifier", task.verifier
        return "environment", task.environment
    raise SystemExit(f"FAIL unknown phase {phase}")


def policy_document(policy: Policy) -> str:
    if policy.mode == "public":
        return '{"mode":"allow-all"}'
    if policy.mode == "no-network":
        return '{"mode":"deny-all"}'
    hosts = ",".join(f'"{host}"' for host in policy.hosts)
    return f'{{"mode":"deny-all","allowNetworks":[{hosts}]}}'


def emit(line: str, expect: str | None = None) -> None:
    if expect is not None:
        require(expect in line, f"{line} != {expect}")
    print(line)


def run_scenario(
    title: str,
    target: str,
    task_name: str,
    expect_error: str | None,
    steps: tuple[tuple[str, str, str, str], ...],
) -> None:
    print(f"== {title} ==")
    task = load_task(task_name)
    error = validate(target, task)
    if expect_error is not None:
        require(error == expect_error, f"{title} error {error!r}")
        require(steps == (), f"{title} ran after reject")
        emit(f"validate reject target={target} {error}")
        return
    require(error is None, f"{title} unexpected {error}")
    emit(f"validate ok target={target}")
    restricted = task.environment.mode != "public"
    emit(f"restrict_before_build {str(restricted).lower()}")
    for phase, method, host, expect in steps:
        if phase == "filesystem":
            line = f"filesystem {method} {host} network=skip reward_hack_file=unblocked"
            require(line.endswith(expect), line)
            print(line)
            continue
        if phase == "image_pull":
            require(restricted, f"{title} pulled under a public baseline")
            line = "image_pull order=before-apply_network_policy"
            require(line == expect, line)
            print(line)
            continue
        source, policy = active(task, phase)
        decision = decide(policy, host)
        line = f"{phase} {method} {host} via {source}:{policy.mode} -> {decision}"
        require(line.endswith(f"-> {expect}"), f"{line} != {expect}")
        print(line)


def main() -> None:
    allowlist_reject = (
        "network_mode='allowlist' is not supported by sbx environment. " + REJECT_TAIL
    )
    wildcard_reject = (
        "network_mode='allowlist' with wildcard hostnames is not supported by sbx "
        f"environment. {REJECT_TAIL}"
    )
    ipv4_reject = (
        "network_mode='allowlist' with IPv4 addresses is not supported by sbx "
        f"environment. {REJECT_TAIL}"
    )
    cidr_reject = (
        "network_mode='allowlist' with IPv4 CIDR ranges is not supported by sbx "
        f"environment. {REJECT_TAIL}"
    )
    print(f"python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print("simulator harbor-sbx-network-phases")
    print(f"rules-from harbor main {SHA}")
    print("scope local-policy-simulator")
    print("not-run harbor sbx microvm compose dogwood")
    print("local-machine-sandbox-policy not-applied")
    print("policy-store-ack is-not-enforcement-barrier")

    run_scenario(
        "cloud phase-split",
        "cloud",
        "phase-split",
        None,
        (
            ("dockerfile_build", "GET", "pypi.org", "allow"),
            ("agent_setup", "GET", "files.pythonhosted.org", "allow"),
            ("agent_setup", "GET", "pypi.org", "allow"),
            ("agent_run", "GET", "api.openai.com", "allow"),
            ("agent_run", "GET", "pypi.org", "allow"),
            ("agent_run", "GET", "files.pythonhosted.org", "deny"),
            ("agent_run", "GET", "stackoverflow.com", "deny"),
            ("agent_run", "GET", "gist.githubusercontent.com", "deny"),
            ("agent_run", "POST", "pastebin.example", "deny"),
            ("agent_run", "GET", "api.openai.com.evil.example", "deny"),
            ("agent_run", "GET", "openai.com", "deny"),
            ("verifier", "GET", "api.openai.com", "deny"),
            ("verifier", "GET", "pypi.org", "deny"),
            ("filesystem", "write", "tests/test_solution.py", "network=skip reward_hack_file=unblocked"),
            ("filesystem", "write", "/tmp/score.json", "network=skip reward_hack_file=unblocked"),
        ),
    )
    phase_split = load_task("phase-split")
    assert phase_split.agent is not None
    emit(
        "policy-document agent " + policy_document(phase_split.agent),
        '{"mode":"deny-all","allowNetworks":["pypi.org","api.openai.com"]}',
    )

    run_scenario(
        "local phase-split",
        "local",
        "phase-split",
        allowlist_reject,
        (),
    )
    run_scenario(
        "local phase-no-network",
        "local",
        "phase-no-network",
        dynamic_error("agent"),
        (),
    )
    run_scenario(
        "local static-public",
        "local",
        "static-public",
        None,
        (
            ("agent_setup", "GET", "pypi.org", "allow"),
            ("agent_run", "GET", "stackoverflow.com", "allow"),
        ),
    )
    run_scenario(
        "local static-no-network",
        "local",
        "static-no-network",
        None,
        (
            ("agent_setup", "GET", "pypi.org", "deny"),
            ("agent_run", "GET", "stackoverflow.com", "deny"),
        ),
    )
    emit(
        "local-apply mode=public ValueError: Local SBX only supports a static no-network policy",
        "Local SBX only supports a static no-network policy",
    )
    emit(
        "local-apply mode=no-network source-command sbx policy deny network --sandbox <sandbox> **",
        "source-command sbx policy deny network",
    )
    run_scenario("cloud wildcard", "cloud", "wildcard", wildcard_reject, ())
    emit(
        "mapper-if-called " + policy_document(load_task("wildcard").environment),
        '{"mode":"deny-all","allowNetworks":["*.pypi.org"]}',
    )
    run_scenario("cloud ipv4", "cloud", "ipv4", ipv4_reject, ())
    run_scenario("cloud cidr", "cloud", "cidr", cidr_reject, ())
    run_scenario(
        "cloud empty-allowlist",
        "cloud",
        "empty-allowlist",
        None,
        (
            ("agent_setup", "GET", "pypi.org", "allow"),
            ("agent_run", "GET", "api.openai.com", "deny"),
        ),
    )
    run_scenario(
        "cloud build-allowlist",
        "cloud",
        "build-allowlist",
        None,
        (
            ("image_pull", "GET", "pypi.org", "image_pull order=before-apply_network_policy"),
            ("dockerfile_build", "GET", "pypi.org", "deny"),
            ("dockerfile_build", "GET", "api.openai.com", "allow"),
        ),
    )
    run_scenario(
        "cloud verifier-inherits-public",
        "cloud",
        "verifier-inherits",
        None,
        (("verifier", "GET", "stackoverflow.com", "allow"),),
    )
    print("checks passed")


if __name__ == "__main__":
    main()
