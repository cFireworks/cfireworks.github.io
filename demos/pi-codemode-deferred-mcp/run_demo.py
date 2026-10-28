#!/usr/bin/env python3
"""Contract sketch of Pi Codemode's deferred MCP path.

This is not Pi, not QuickJS, and not an MCP session. It models a few
numbers from the docs I read on 2026-10-10:

- Prompt-token estimates use characters / 4, the estimator named for
  codemode.inlineBudget in the settings reference.
- Default MCP exposure keeps tool schemas out of the codemode description.
  The system prompt gets one line per server. This file renders that line
  itself; it is not a quote of Pi's prompt template.
- searchTools is documented as BM25 with a default limit of 8. Pi does not
  publish k1, b, or the tokenizer. The ranker below is Okapi BM25 on this
  toy corpus only (k1=1.5, b=0.75, tokens [a-z0-9_]+).
- The script path filters structured records and returns a short JSON value.
  Frustration markers are a fixed substring list, not a classifier.
- A second server shape returns structured JSON for a 5-item probe and prose
  for the full batch. That is this file's stand-in for an inconsistent
  result, not a trace from a live server.
- Nested encoding measures json.dumps of a code string, then json.dumps of
  that text again. Pi's codemode tool input is raw JavaScript, so the outer
  script is not itself JSON. The second encoding is the crutch of putting a
  code string through another JSON tool call.
- Every synthetic tool schema also carries cursor, pageSize, and locale, so
  the dump has a visible per-tool floor. Those three fields are not claimed
  to exist on Linear, Sentry, or the other names used below.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter

K1 = 1.5
B = 0.75
INLINE_BUDGET = 3000
SEARCH_LIMIT = 8
TOKEN_RE = re.compile(r"[a-z0-9_]+")
MARKERS = ("frustrating", "stuck", "pain")
FLAGGED_INDEXES = (0, 5, 11, 17, 22)


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"check failed: {message}")


def est_tokens(text: str) -> float:
    """Pi settings: estimated tokens are characters / 4."""
    return len(text) / 4


def fmt_tokens(text: str) -> str:
    return f"chars={len(text)} tokens={est_tokens(text):.2f}"


def tool_id(server: str, name: str) -> str:
    return f"mcp__{server.replace('-', '_')}__{name}"


def schema(fields: list[tuple[str, str, str, bool]]) -> dict:
    properties = {}
    required = []
    for name, typ, desc, req in fields:
        properties[name] = {"type": typ, "description": desc}
        if req:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


PAGINATION = (
    ("cursor", "string", "Opaque pagination cursor returned by the previous page.", False),
    ("pageSize", "integer", "Page size. The server may cap this and say so in the result.", False),
    ("locale", "string", "BCP 47 language tag for human-readable fields in the result.", False),
)


def server(name: str, description: str, tools: list[tuple]) -> dict:
    built = []
    for tool_name, tool_desc, fields in tools:
        built.append(
            {
                "name": tool_name,
                "description": tool_desc,
                "schema": schema([*fields, *PAGINATION]),
            }
        )
    return {"name": name, "description": description, "tools": built}


SERVERS = [
    server(
        "linear",
        "Linear issues, comments, and projects for one workspace.",
        [
            (
                "list_issues",
                "List open Linear issues for a team, with identifier and title.",
                [
                    ("team", "string", "Team key, for example Pi.", True),
                    ("state", "string", "Workflow state name. Use open for the backlog.", False),
                    ("limit", "integer", "Maximum issues to return.", False),
                ],
            ),
            (
                "list_comments",
                "List comments on one Linear issue.",
                [
                    ("issueId", "string", "Issue identifier such as PI-1000.", True),
                ],
            ),
            (
                "get_issue",
                "Fetch one Linear issue by identifier.",
                [("issueId", "string", "Issue identifier.", True)],
            ),
            (
                "search_issues",
                "Search Linear issue titles by keyword.",
                [("query", "string", "Keyword query.", True)],
            ),
            (
                "create_comment",
                "Add a comment to a Linear issue.",
                [
                    ("issueId", "string", "Issue identifier.", True),
                    ("body", "string", "Comment text.", True),
                ],
            ),
            (
                "list_projects",
                "List Linear projects in the workspace.",
                [("limit", "integer", "Maximum projects to return.", False)],
            ),
        ],
    ),
    server(
        "sentry",
        "Sentry organizations, projects, and unresolved issues.",
        [
            (
                "find_organizations",
                "List Sentry organizations visible to the token.",
                [],
            ),
            (
                "find_projects",
                "List projects in one Sentry organization.",
                [("organizationSlug", "string", "Organization slug.", True)],
            ),
            (
                "list_issues",
                "List unresolved Sentry issues in a project.",
                [("projectSlug", "string", "Project slug.", True)],
            ),
            (
                "get_issue",
                "Fetch one Sentry issue by id.",
                [("issueId", "string", "Sentry issue id.", True)],
            ),
            (
                "list_events",
                "List events attached to one Sentry issue.",
                [("issueId", "string", "Sentry issue id.", True)],
            ),
            (
                "list_releases",
                "List releases for a Sentry project.",
                [("projectSlug", "string", "Project slug.", True)],
            ),
        ],
    ),
    server(
        "github",
        "GitHub issues, pull requests, and commits for one repository.",
        [
            (
                "list_issues",
                "List GitHub issues in a repository.",
                [
                    ("owner", "string", "Repository owner.", True),
                    ("repo", "string", "Repository name.", True),
                ],
            ),
            (
                "list_pulls",
                "List pull requests in a repository.",
                [
                    ("owner", "string", "Repository owner.", True),
                    ("repo", "string", "Repository name.", True),
                ],
            ),
            (
                "get_issue",
                "Fetch one GitHub issue.",
                [("number", "integer", "Issue number.", True)],
            ),
            (
                "list_comments",
                "List comments on a GitHub issue.",
                [("number", "integer", "Issue number.", True)],
            ),
            (
                "search_code",
                "Search code in a repository.",
                [("query", "string", "Code search query.", True)],
            ),
            (
                "list_commits",
                "List commits on a branch.",
                [("sha", "string", "Branch or commit SHA.", True)],
            ),
        ],
    ),
    server(
        "docs",
        "Product documentation and API reference pages.",
        [
            ("search", "Search product documentation pages.", [("query", "string", "Search query.", True)]),
            ("get_page", "Read one documentation page by path.", [("path", "string", "Page path.", True)]),
            ("list_sections", "List documentation sections.", []),
            ("get_changelog", "Read the product changelog.", []),
            ("search_api", "Search API reference pages.", [("query", "string", "API search query.", True)]),
            (
                "get_endpoint",
                "Read one API endpoint page.",
                [("path", "string", "Endpoint path.", True)],
            ),
        ],
    ),
    server(
        "billing",
        "Invoices, usage records, and the current subscription.",
        [
            ("list_invoices", "List invoices for the account.", []),
            ("get_invoice", "Fetch one invoice.", [("invoiceId", "string", "Invoice id.", True)]),
            (
                "list_usage",
                "List usage records for a period.",
                [
                    ("start", "string", "Period start, YYYY-MM-DD.", True),
                    ("end", "string", "Period end, YYYY-MM-DD.", True),
                ],
            ),
            ("get_subscription", "Read the current subscription.", []),
            ("list_credits", "List credit balance entries.", []),
            ("get_tax_id", "Read the tax identifier on the account.", []),
        ],
    ),
    server(
        "slack",
        "Workspace channels, users, and recent messages.",
        [
            ("list_channels", "List channels in the workspace.", []),
            (
                "history",
                "Read recent messages in a channel.",
                [("channel", "string", "Channel id.", True)],
            ),
            (
                "search_messages",
                "Search messages across the workspace.",
                [("query", "string", "Message query.", True)],
            ),
            ("list_users", "List workspace users.", []),
            ("get_user", "Fetch one user profile.", [("userId", "string", "User id.", True)]),
            (
                "post_message",
                "Post a message to a channel.",
                [
                    ("channel", "string", "Channel id.", True),
                    ("text", "string", "Message text.", True),
                ],
            ),
        ],
    ),
]

EXTRA = server(
    "status",
    "Public status page incidents for the same product.",
    [
        ("list_incidents", "List recent status incidents.", []),
        ("get_incident", "Fetch one incident.", [("incidentId", "string", "Incident id.", True)]),
        ("list_components", "List status components.", []),
        ("get_component", "Fetch one component.", [("componentId", "string", "Component id.", True)]),
        ("list_maintenances", "List scheduled maintenance windows.", []),
        ("get_summary", "Read the current status summary.", []),
    ],
)

BUILTIN_DECLS = [
    "/** Read a file. */\ndeclare function read(args: { path: string }): Promise<string>;",
    "/** Run a shell command. */\ndeclare function bash(args: { command: string }): Promise<{ output: string; exit_code: number }>;",
    "/** Replace text in a file. */\ndeclare function edit(args: { path: string; oldText: string; newText: string }): Promise<string>;",
    "/** Write a file. */\ndeclare function write(args: { path: string; content: string }): Promise<string>;",
]

CALM = (
    "The steps in the README match what I see.",
    "Reproduced on the 1.0.0 build and attached the log.",
    "Happy to retest after the next release.",
    "This is a factual report with no extra context.",
)
HOT_COMMENTS = {
    0: "This is frustrating: the TUI stays on Working.",
    5: "High CPU in a long session is a pain.",
    11: "The missing update command leaves the session stuck.",
    17: "The wrapped sign-in URL is frustrating to open.",
    22: "Waiting on direct tools at the first prompt is a pain.",
}
TITLES = (
    "TUI stays on Working after Esc",
    "Context window defaults to 128k",
    "Add an install section to the README",
    "Windows sink thread notes",
    "Reload drops a custom tool",
    "High CPU during long sessions",
    "Theme preview repaints too often",
    "Session file appears before the reply",
    "OAuth callback port already in use",
    "Paste inserts a file icon",
    "Footer usage cache",
    "Update command from the TUI",
    "Provider alias in the model picker",
    "Quiet startup hides the model line",
    "Fullscreen scrollback request",
    "Resource list omits ui URIs",
    "Collapsed JSON fills the screen",
    "Sign-in URL wraps and is hard to open",
    "Project mcp.json replaces the user entry",
    "Tool search keeps a loaded tool on the branch",
    "Image block rejected by the provider",
    "Classifier cost on the script result",
    "First prompt waits on direct tools only",
    "Namespace accepts a hyphen or an underscore",
)


def dump_tool(server_name: str, tool: dict) -> str:
    body = {
        "name": tool_id(server_name, tool["name"]),
        "description": tool["description"],
        "inputSchema": tool["schema"],
    }
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def dump_all(servers: list[dict]) -> str:
    lines = [dump_tool(item["name"], tool) for item in servers for tool in item["tools"]]
    return "\n".join(lines)


def without_shared_fields(servers: list[dict]) -> list[dict]:
    """Drop the three fields added to every tool. Same order, same other text."""
    stripped = []
    for item in servers:
        tools = []
        for tool in item["tools"]:
            properties = {
                key: value
                for key, value in tool["schema"]["properties"].items()
                if key not in {"cursor", "pageSize", "locale"}
            }
            required = [key for key in tool["schema"]["required"] if key in properties]
            tools.append(
                {
                    "name": tool["name"],
                    "description": tool["description"],
                    "schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }
            )
        stripped.append({**item, "tools": tools})
    return stripped


def one_line(item: dict, exposure: str = "codemode") -> str:
    return f"- {item['name']} ({exposure}): {item['description']}"


def one_lines(servers: list[dict]) -> str:
    return "\n".join(one_line(item) for item in servers)


def declaration(server_name: str, tool: dict) -> str:
    """TypeScript-shaped declaration this demo would inline. Not Pi's formatter."""
    required = set(tool["schema"]["required"])
    ident = tool_id(server_name, tool["name"])
    lines = [f"/** {tool['description']} */", f"declare function {ident}(args: {{"]
    for name, spec in tool["schema"]["properties"].items():
        ts = "number" if spec["type"] == "integer" else spec["type"]
        optional = "" if name in required else "?"
        lines.append(f"  /** {spec['description']} */")
        lines.append(f"  {name}{optional}: {ts};")
    lines.append("}): Promise<CallToolResult>;")
    return "\n".join(lines)


def all_decls(servers: list[dict]) -> list[str]:
    return [declaration(item["name"], tool) for item in servers for tool in item["tools"]]


def pack(decls: list[str], budget: float) -> tuple[int, float]:
    used = 0.0
    kept = 0
    for text in decls:
        cost = est_tokens(text)
        if kept and used + cost > budget:
            break
        if not kept and cost > budget:
            break
        used += cost
        kept += 1
    return kept, budget - used


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


def search_tools(servers: list[dict], query: str, limit: int = SEARCH_LIMIT) -> list[dict]:
    docs = []
    for item in servers:
        for tool in item["tools"]:
            ident = tool_id(item["name"], tool["name"])
            text = f"{ident} {tool['description']}"
            docs.append(
                {
                    "name": ident,
                    "description": tool["description"],
                    "tokens": tokenize(text),
                }
            )
    avgdl = sum(len(doc["tokens"]) for doc in docs) / len(docs)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc["tokens"]))
    n_docs = len(docs)
    query_terms = tokenize(query)
    ranked = []
    for doc in docs:
        counts = Counter(doc["tokens"])
        score = 0.0
        for term in query_terms:
            freq = counts[term]
            if freq == 0:
                continue
            idf = math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1)
            denom = freq + K1 * (1 - B + B * len(doc["tokens"]) / avgdl)
            score += idf * (freq * (K1 + 1)) / denom
        ranked.append((score, doc["name"], doc["description"]))
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return [
        {"name": name, "description": desc, "score": score}
        for score, name, desc in ranked[:limit]
        if score > 0
    ]


def make_issues() -> list[dict]:
    issues = []
    for index, title in enumerate(TITLES):
        comments = [
            f"Issue note A: reproduced against the 1.0.0 build ({index}).",
            f"Issue note B: log attached, no extra context ({index}).",
            HOT_COMMENTS[index] if index in HOT_COMMENTS else CALM[index % len(CALM)],
        ]
        issues.append(
            {
                "identifier": f"PI-{1000 + index}",
                "title": title,
                "state": "open",
                "comments": comments,
            }
        )
    return issues


def json_len(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def flagged(issue: dict) -> bool:
    blob = " ".join(issue["comments"]).lower()
    return any(marker in blob for marker in MARKERS)


def run_script(issues: list[dict]) -> dict:
    summary = [{"identifier": item["identifier"], "title": item["title"]} for item in issues]
    summary_chars = json_len(summary)
    print(f"list_issues structured compact {fmt_tokens(json.dumps(summary, ensure_ascii=False, separators=(',', ':')))}")
    buckets = [[] for _ in range(4)]
    for index, issue in enumerate(issues):
        buckets[index % 4].append(issue)
    intermediate = summary_chars
    for worker, bucket in enumerate(buckets):
        comments = [
            {"issueId": issue["identifier"], "comments": issue["comments"]} for issue in bucket
        ]
        size = json_len(comments)
        intermediate += size
        ids = ",".join(issue["identifier"] for issue in bucket)
        print(f"worker {worker} issues={len(bucket)} ids={ids} comment_chars={size}")
    kept = [issue for issue in issues if flagged(issue)]
    result = {
        "total": len(issues),
        "counts": {"flagged": len(kept), "calm": len(issues) - len(kept)},
        "flagged": [f"{issue['identifier']} {issue['title']}" for issue in kept],
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(f"intermediate_chars={intermediate} tokens={intermediate / 4:.2f}")
    print(f"return {fmt_tokens(rendered)}")
    print(f"return_over_intermediate={len(rendered) / intermediate:.4f}")
    print(rendered)
    return result


def prose_batch(issues: list[dict]) -> str:
    lines = [f"Showing {len(issues)} issues (rewritten as prose for a dump-everything client):"]
    for issue in issues:
        lines.append(f"{issue['identifier']} {issue['title']}. " + " ".join(issue["comments"]))
    return "\n".join(lines)


def probe_shapes(issues: list[dict]) -> None:
    probe = issues[:5]
    probe_json = json.dumps(
        [{"identifier": item["identifier"], "title": item["title"]} for item in probe],
        ensure_ascii=False,
    )
    parsed = json.loads(probe_json)
    print(f"probe limit=5 json_ok count={len(parsed)} {fmt_tokens(probe_json)}")
    prose = prose_batch(issues)
    try:
        json.loads(prose)
    except json.JSONDecodeError as exc:
        print(f"full batch prose json_ok=false error={exc.msg} {fmt_tokens(prose)}")
    else:
        raise SystemExit("check failed: prose batch parsed as JSON")


def nested_encoding() -> None:
    inner = (
        "async () => {\n"
        '  const r = await cloudflare.request({ method: "GET", path: "/accounts" });\n'
        "  return r.result.map((a) => ({ id: a.id, name: a.name }));\n"
        "}"
    )
    wire = json.dumps({"code": inner}, ensure_ascii=False)
    twice = json.dumps(wire, ensure_ascii=False)
    print(f"inner_js {fmt_tokens(inner)}")
    print(f"once_json {fmt_tokens(wire)}")
    print(f"twice_json {fmt_tokens(twice)}")
    print(f"twice_head={twice[:140]}")
    require(len(twice) > len(wire) > len(inner), "encoding did not grow")


def main() -> None:
    print(f"python {sys.version.split()[0]}")
    print("scope simulation=contract pi=false quickjs=false mcp_transport=false network=false")
    print("estimator characters/4 source=pi settings codemode.inlineBudget")
    print(
        f"search bm25 k1={K1} b={B} limit={SEARCH_LIMIT} "
        "corpus=this file only pi_ranker=false"
    )

    print("== inventory ==")
    dumped = dump_all(SERVERS)
    lines = one_lines(SERVERS)
    tool_count = sum(len(item["tools"]) for item in SERVERS)
    print(f"servers={len(SERVERS)} tools={tool_count}")
    print(f"dump_all {fmt_tokens(dumped)}")
    bare = dump_all(without_shared_fields(SERVERS))
    print(f"dump_without_shared_fields {fmt_tokens(bare)}")
    print(
        "shared_fields_delta_tokens="
        f"{est_tokens(dumped) - est_tokens(bare):.2f}"
    )
    print(
        f"dump_over_one_line={est_tokens(dumped) / est_tokens(lines):.2f} "
        f"bare_over_one_line={est_tokens(bare) / est_tokens(lines):.2f}"
    )
    print(f"one_line {fmt_tokens(lines)}")
    print(lines)
    for item in SERVERS:
        portion = "\n".join(dump_tool(item["name"], tool) for tool in item["tools"])
        print(f"server {item['name']} tools={len(item['tools'])} dump_{fmt_tokens(portion)}")

    print("== connect status ==")
    with_extra = SERVERS + [EXTRA]
    dumped_extra = dump_all(with_extra)
    lines_extra = one_lines(with_extra)
    print(
        "dump_tokens "
        f"{est_tokens(dumped):.2f} -> {est_tokens(dumped_extra):.2f} "
        f"delta={est_tokens(dumped_extra) - est_tokens(dumped):.2f}"
    )
    print(
        "one_line_tokens "
        f"{est_tokens(lines):.2f} -> {est_tokens(lines_extra):.2f} "
        f"delta={est_tokens(lines_extra) - est_tokens(lines):.2f}"
    )
    dump_delta = est_tokens(dumped_extra) - est_tokens(dumped)
    line_delta = est_tokens(lines_extra) - est_tokens(lines)
    bare_extra = dump_all(without_shared_fields(with_extra))
    bare_delta = est_tokens(bare_extra) - est_tokens(bare)
    print(
        "bare_dump_tokens "
        f"{est_tokens(bare):.2f} -> {est_tokens(bare_extra):.2f} "
        f"delta={bare_delta:.2f}"
    )
    print(f"dump_delta_over_line_delta={dump_delta / line_delta:.2f}")
    print(f"bare_delta_over_line_delta={bare_delta / line_delta:.2f}")
    print(f"added_line={one_line(EXTRA)}")
    print("codemode_description_listed_mcp_decls=0 exposure=codemode")

    print("== inline budget ==")
    decls = all_decls(SERVERS)
    kept, left = pack(decls, INLINE_BUDGET)
    print(f"budget={INLINE_BUDGET} order=server_then_tool")
    print(f"mcp_decls_fitting={kept} of {len(decls)} leftover={left:.2f}")
    builtin_kept, builtin_left = pack(BUILTIN_DECLS + decls, INLINE_BUDGET)
    print(
        f"after_four_builtins fitting={builtin_kept} of {len(BUILTIN_DECLS) + len(decls)} "
        f"leftover={builtin_left:.2f}"
    )
    require(kept < len(decls), "every MCP declaration fit in 3000")

    print("== script ==")
    query = "list open linear issues"
    hits = search_tools(SERVERS, query)
    print(f"searchTools query={query!r} hits={len(hits)}")
    for index, hit in enumerate(hits, start=1):
        print(f"{index}. {hit['score']:.3f} {hit['name']} | {hit['description']}")
    require(hits, "search returned nothing")
    chosen = hits[0]["name"]
    require(chosen == "mcp__linear__list_issues", f"unexpected top hit {chosen}")
    linear = next(item for item in SERVERS if item["name"] == "linear")
    list_tool = next(tool for tool in linear["tools"] if tool["name"] == "list_issues")
    decl = declaration("linear", list_tool)
    print(f"describeTool {chosen} {fmt_tokens(decl)}")
    print(decl)
    names = [tool["name"] for tool in linear["tools"]]
    print(
        "describeNamespace mcp__linear "
        f"description={linear['description']!r} tools={','.join(names)}"
    )
    require(set(HOT_COMMENTS) == set(FLAGGED_INDEXES), "flagged indexes")
    issues = make_issues()
    result = run_script(issues)
    require(result["counts"]["flagged"] == len(FLAGGED_INDEXES), "flagged count")
    require(result["total"] == 24, "issue count")

    print("== text shape ==")
    probe_shapes(issues)

    print("== nested encoding ==")
    nested_encoding()
    print("inner_calls_outer_tools=false modeled_only=true")
    print("checks passed")


if __name__ == "__main__":
    main()
