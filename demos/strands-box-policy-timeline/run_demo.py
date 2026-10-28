#!/usr/bin/env python3
"""Local counterpart of the Strands Box Slack timeline.

The AWS Open Source Blog post on 2026-10-07 shows a Dogwood forbid: at most
three HTTP 200 responses for POST https://slack.com/api/chat.postMessage in
any 10 minutes. This script parses the shortened box.toml and policy.dw next
to it, then applies that one limit with a Python counter.

It is not the Dogwood Local Engine. It does not start `box run`, Seatbelt,
Slack, or AWS. A window edge of exactly 600 seconds is included because the
Dogwood guide describes a closed interval; that row is not in the blog table,
and this script did not replay it through the dogwood CLI.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DAY = "2026-10-14"
UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


@dataclass(frozen=True)
class Match:
    host_eq: str | None = None
    host_like: str | None = None
    port: int | None = None
    method: str | None = None
    path: str | None = None

    def hits(self, host: str, port: int, method: str, path: str) -> bool:
        if self.host_eq is not None and host != self.host_eq:
            return False
        if self.host_like is not None and not like(self.host_like, host):
            return False
        if self.port is not None and port != self.port:
            return False
        if self.method is not None and method != self.method:
            return False
        if self.path is not None and path != self.path:
            return False
        return True


@dataclass(frozen=True)
class Rule:
    rule_id: str
    effect: str
    action: str
    temporal: bool
    description: str
    request: Match
    status: int | None = None
    window_label: str | None = None
    window_seconds: int | None = None
    threshold: int | None = None


@dataclass(frozen=True)
class Response:
    at: datetime
    host: str
    port: int
    method: str
    path: str
    status: int


@dataclass(frozen=True)
class Attempt:
    clock: str
    host: str
    port: int
    method: str
    path: str
    status: int
    expect: str
    expect_rule: str
    expect_prior: int


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def like(pattern: str, value: str) -> bool:
    """Local subset of a single-star pattern. Not Cedar's like."""
    parts = pattern.split("*")
    return re.fullmatch(".*".join(re.escape(part) for part in parts), value) is not None


def strip_comments(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if "//" in line:
            line = line[: line.index("//")]
        kept.append(line)
    return "\n".join(kept)


def parse_match(block: str) -> Match:
    host_eq = re.search(r'context\.input\.host\s*==\s*"([^"]+)"', block)
    host_like = re.search(r'context\.input\.host\s+like\s+"([^"]+)"', block)
    if host_eq is None and host_like is None:
        host_eq = re.search(r'input\.host:\s*"([^"]+)"', block)
    port = re.search(r"(?:context\.)?input\.port\s*(?:==|:)\s*(\d+)", block)
    method = re.search(
        r'(?:context\.)?input\.method\s*(?:==|:)\s*"([^"]+)"', block
    )
    path = re.search(r'(?:context\.)?input\.path\s*(?:==|:)\s*"([^"]+)"', block)
    return Match(
        host_eq=host_eq.group(1) if host_eq else None,
        host_like=host_like.group(1) if host_like else None,
        port=int(port.group(1)) if port else None,
        method=method.group(1) if method else None,
        path=path.group(1) if path else None,
    )


def parse_policy(text: str) -> list[Rule]:
    body = strip_comments(text)
    parts = re.split(r'@id\("([^"]+)"\)', body)
    require(len(parts) >= 3 and len(parts) % 2 == 1, "policy has no @id rules")
    rules: list[Rule] = []
    for rule_id, chunk in zip(parts[1::2], parts[2::2]):
        effect_match = re.search(r"\b(permit|forbid)\b", chunk)
        action_match = re.search(r'Box::Action::"([^"]+)"', chunk)
        require(effect_match is not None, f"{rule_id} has no permit or forbid")
        require(action_match is not None, f"{rule_id} has no action")
        description_match = re.search(r'@description\("([^"]*)"\)', chunk)
        temporal = "when temporal" in chunk
        request_block = chunk.split("when temporal", 1)[0]
        status = None
        window_label = None
        window_seconds = None
        threshold = None
        if temporal:
            response = chunk.split("::response", 1)
            require(len(response) == 2, f"{rule_id} temporal clause has no ::response")
            request_block = response[0]
            window = re.search(r"within\s+(\d+)([smhd])\b", chunk)
            limit = re.search(r">=\s*(\d+)", chunk)
            status_match = re.search(r"output\.status:\s*(\d+)", chunk)
            require(window is not None, f"{rule_id} has no within window")
            require(limit is not None, f"{rule_id} has no >= threshold")
            require(status_match is not None, f"{rule_id} has no output.status")
            amount = int(window.group(1))
            window_label = f"{amount}{window.group(2)}"
            window_seconds = amount * UNITS[window.group(2)]
            threshold = int(limit.group(1))
            status = int(status_match.group(1))
        rules.append(
            Rule(
                rule_id=rule_id,
                effect=effect_match.group(1),
                action=action_match.group(1),
                temporal=temporal,
                description=description_match.group(1) if description_match else "",
                request=parse_match(request_block),
                status=status,
                window_label=window_label,
                window_seconds=window_seconds,
                threshold=threshold,
            )
        )
    return rules


def load_box(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def clock_at(clock: str) -> datetime:
    return datetime.strptime(f"{DAY} {clock}", "%Y-%m-%d %H:%M:%S")


def prior_hits(rule: Rule, history: list[Response], now: datetime) -> int:
    require(rule.window_seconds is not None and rule.status is not None, "temporal rule incomplete")
    window = timedelta(seconds=rule.window_seconds)
    total = 0
    for item in history:
        age = now - item.at
        if age < timedelta(0) or age > window:
            continue
        if item.status != rule.status:
            continue
        if rule.request.hits(item.host, item.port, item.method, item.path):
            total += 1
    return total


def decide(
    rules: list[Rule], history: list[Response], attempt: Attempt
) -> tuple[str, str, int]:
    limit = next(rule for rule in rules if rule.rule_id == "rate_limit_slack_posts")
    prior = prior_hits(limit, history, clock_at(attempt.clock))
    applicable = [
        rule
        for rule in rules
        if rule.action == "http:request"
        and rule.request.hits(attempt.host, attempt.port, attempt.method, attempt.path)
    ]
    temporal = [rule for rule in applicable if rule.effect == "forbid" and rule.temporal]
    permits = [rule for rule in applicable if rule.effect == "permit"]
    if temporal and prior >= (temporal[0].threshold or 0):
        return "Deny", temporal[0].rule_id, prior
    if permits:
        return "Allow", permits[0].rule_id, prior
    return "Deny", "deny-by-default", prior


def run_rows(rules: list[Rule], attempts: list[Attempt]) -> list[str]:
    history: list[Response] = []
    lines: list[str] = []
    for attempt in attempts:
        decision, rule_id, prior = decide(rules, history, attempt)
        require(decision == attempt.expect, f"{attempt.clock} decision {decision}")
        require(rule_id == attempt.expect_rule, f"{attempt.clock} rule {rule_id}")
        require(prior == attempt.expect_prior, f"{attempt.clock} prior {prior}")
        lines.append(
            f"{attempt.clock} {attempt.method} {attempt.host}{attempt.path} "
            f"upstream={attempt.status} prior_200={prior} {decision} {rule_id}"
        )
        if decision == "Allow":
            history.append(
                Response(
                    at=clock_at(attempt.clock),
                    host=attempt.host,
                    port=attempt.port,
                    method=attempt.method,
                    path=attempt.path,
                    status=attempt.status,
                )
            )
    return lines


def blog_attempts() -> list[Attempt]:
    slack = ("slack.com", 443, "POST", "/api/chat.postMessage")
    logs = ("logs.us-west-2.amazonaws.com", 443, "GET", "/")
    rows = [
        ("10:00:00", slack, 200, "Allow", "allow_slack_post", 0),
        ("10:03:00", slack, 200, "Allow", "allow_slack_post", 1),
        ("10:05:00", slack, 200, "Allow", "allow_slack_post", 2),
        ("10:06:00", slack, 200, "Deny", "rate_limit_slack_posts", 3),
        ("10:07:00", logs, 200, "Allow", "allow_https_to_aws", 3),
        ("10:11:00", slack, 200, "Allow", "allow_slack_post", 2),
    ]
    return [pack(row) for row in rows]


def extra_attempts() -> list[Attempt]:
    slack = ("slack.com", 443, "POST", "/api/chat.postMessage")
    other = ("slack.com", 443, "POST", "/api/chat.update")
    rows = [
        ("10:00:00", slack, 200, "Allow", "allow_slack_post", 0),
        ("10:01:00", slack, 500, "Allow", "allow_slack_post", 1),
        ("10:02:00", slack, 200, "Allow", "allow_slack_post", 1),
        ("10:03:00", slack, 200, "Allow", "allow_slack_post", 2),
        ("10:04:00", slack, 200, "Deny", "rate_limit_slack_posts", 3),
        ("10:04:30", ("example.com", 443, "GET", "/"), 200, "Deny", "deny-by-default", 3),
        ("10:05:00", other, 200, "Deny", "deny-by-default", 3),
    ]
    return [pack(row) for row in rows]


def edge_attempts() -> list[Attempt]:
    slack = ("slack.com", 443, "POST", "/api/chat.postMessage")
    rows = [
        ("10:00:00", slack, 200, "Allow", "allow_slack_post", 0),
        ("10:00:01", slack, 200, "Allow", "allow_slack_post", 1),
        ("10:00:02", slack, 200, "Allow", "allow_slack_post", 2),
        ("10:10:00", slack, 200, "Deny", "rate_limit_slack_posts", 3),
        ("10:10:03", slack, 200, "Allow", "allow_slack_post", 0),
    ]
    return [pack(row) for row in rows]


def pack(row: tuple) -> Attempt:
    clock, target, status, expect, rule, prior = row
    host, port, method, path = target
    return Attempt(clock, host, port, method, path, status, expect, rule, prior)


def render(box: dict, rules: list[Rule]) -> str:
    slack = box["egress"]["slack"]
    aws = box["egress"]["aws"]
    lines = [
        f"box.toml name={box['name']} policy={box['policy']}",
        (
            "egress.slack destinations="
            + ",".join(slack["destinations"])
            + f" secret.ref={slack['secret']['ref']} inject={slack['secret']['inject']}"
        ),
        (
            "egress.aws destinations="
            + ",".join(aws["destinations"])
            + f" secret.ref={aws['secret']['ref']}"
        ),
        "note egress destination is not a permit; the aws allow comes from policy.dw",
        "note local counterpart of the 2026-10-07 blog timeline; not the Dogwood engine",
        "note Deny does not record upstream; prior_200 counts recorded status 200 only",
    ]
    for rule in rules:
        extra = ""
        if rule.temporal:
            extra = (
                f" window={rule.window_label} status={rule.status} threshold={rule.threshold}"
            )
        lines.append(
            f"rule {rule.rule_id} {rule.effect} {rule.action} temporal={'yes' if rule.temporal else 'no'}{extra}"
        )
    lines.append("== blog ==")
    lines.extend(run_rows(rules, blog_attempts()))
    lines.append("== local extras ==")
    lines.extend(run_rows(rules, extra_attempts()))
    lines.append("== local window edge ==")
    lines.extend(run_rows(rules, edge_attempts()))
    return "\n".join(lines) + "\n"


def main() -> None:
    box = load_box(ROOT / "box.toml")
    rules = parse_policy((ROOT / "policy.dw").read_text(encoding="utf-8"))
    require(box["name"] == "oncall", "box name")
    require(box["policy"] == "policy.dw", "policy path")
    require(box["egress"]["slack"]["secret"]["inject"] == "always", "slack inject")
    ids = [rule.rule_id for rule in rules]
    require(ids == ["allow_https_to_aws", "allow_slack_post", "rate_limit_slack_posts"], "rule ids")
    limit = rules[-1]
    require(limit.effect == "forbid" and limit.temporal, "rate limit shape")
    require(limit.window_seconds == 600, "window")
    require(limit.threshold == 3 and limit.status == 200, "threshold")
    require("Wait before you post again." in limit.description, "description")
    first = render(box, rules)
    second = render(box, rules)
    require(first == second, "two runs diverged")
    print(first, end="")
    print("checks passed")


if __name__ == "__main__":
    main()
