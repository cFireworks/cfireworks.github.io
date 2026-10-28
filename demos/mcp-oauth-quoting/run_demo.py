#!/usr/bin/env python3
"""Inert quoting comparison. No browser, no network, no system shell.

The illustrative URL uses example.test and a subexpression whose only
accepted body is the constant token MARK. This does not launch a client
and does not claim code execution.
"""

from __future__ import annotations

from urllib.parse import urlparse

CURLY_QUOTES = "‘’‚‛"  # U+2018 U+2019 U+201A U+201B
DELIMS = set("'" + CURLY_QUOTES)
URL = "https://example.test/pre-$('MARK')-post"
FILE_URL = "file:///mark.txt"
SCRIPT_SCHEME = "javascript:MARK"


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def expand_marker(body: str) -> str:
    """Expand only $('MARK') or $("MARK"). Any other $( is rejected."""
    out: list[str] = []
    i = 0
    found = 0
    while i < len(body):
        if body.startswith("$(", i):
            found += 1
            rest = body[i + 2 :].lstrip()
            require(rest[:1] in {"'", '"'}, "subexpression must be a quoted MARK")
            quote = rest[0]
            rest = rest[1:]
            require(rest.startswith("MARK" + quote), "subexpression body must be MARK")
            rest = rest[len("MARK") + 1 :].lstrip()
            require(rest.startswith(")"), "subexpression must close")
            consumed = len(body[i + 2 :]) - len(rest[1:])
            out.append("MARK")
            i += 2 + consumed
            continue
        out.append(body[i])
        i += 1
    require(found == 1, "expected one marker subexpression")
    expanded = "".join(out)
    require("$(" not in expanded, "expansion left a subexpression")
    return expanded


def escape_ascii_only(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def escape_full(value: str) -> str:
    chars: list[str] = []
    for ch in value:
        if ch in DELIMS:
            chars.append(ch + ch)
        else:
            chars.append(ch)
    return "'" + "".join(chars) + "'"


def parse_single(src: str) -> tuple[str, str]:
    """One PowerShell-style single-quoted string.

    ASCII and curly quotes all delimit. A delimiter closes unless it is
    doubled. The closer does not have to be the same character as the opener.
    """
    require(src.startswith("'"), "opener must be an ASCII single quote")
    out: list[str] = []
    i = 1
    while i < len(src):
        ch = src[i]
        if ch in DELIMS:
            if i + 1 < len(src) and src[i + 1] == ch:
                out.append(ch)
                i += 2
                continue
            return "".join(out), src[i + 1 :]
        out.append(ch)
        i += 1
    raise SystemExit("FAIL unclosed single-quoted string")


def sdk_denylist_allows(url: str) -> bool:
    """Same three schemes as @modelcontextprotocol/sdk@1.32.0 SafeUrlSchema."""
    scheme = url.split(":", 1)[0].lower() + ":"
    return scheme not in {"javascript:", "data:", "vbscript:"}


def https_allowlist_allows(url: str) -> bool:
    return urlparse(url).scheme in {"http", "https"}


def main() -> None:
    expanded = expand_marker(URL)
    require(expanded == "https://example.test/pre-MARK-post", "double quote expansion")
    print(f"illustrative url: {URL}")
    print(f"double-quoted expansion: {expanded}")

    single = escape_full(URL)
    inside, rest = parse_single(single)
    require(inside == URL, "single quotes keep the marker")
    require(rest == "", "single-quoted value consumed the string")
    require("$('MARK')" in inside, "marker text still present")
    print(f"single-quoted value: {inside}")

    require(sdk_denylist_allows(URL), "https passes the three-scheme denylist")
    require(https_allowlist_allows(URL), "https passes an http/https allowlist")
    require(not sdk_denylist_allows(SCRIPT_SCHEME), "javascript scheme denied")
    require(sdk_denylist_allows(FILE_URL), "file scheme passes the three-scheme denylist")
    require(not https_allowlist_allows(FILE_URL), "file scheme fails the https allowlist")
    print("scheme: https allowed by both gates")
    print("scheme: file allowed by denylist only")
    print("scheme: javascript denied by denylist")

    argv = ["xdg-open", URL]
    require(argv[1] == URL, "argv keeps the url")
    require(expand_marker(argv[1]) != argv[1], "the same bytes expand only after quoting")
    print(f"argv[1] unchanged: {argv[1]}")

    curly = "https://example.test/a" + "\u2019" + "TAIL"
    naive_inside, naive_rest = parse_single(escape_ascii_only(curly))
    require(naive_inside == "https://example.test/a", "curly quote ends an ascii-only wrap")
    require(naive_rest == "TAIL'", "tail sits outside the ascii-only string")
    full_inside, full_rest = parse_single(escape_full(curly))
    require(full_inside == curly, "doubling curly quotes keeps the value")
    require(full_rest == "", "full escape has no tail")
    print("ascii-only escape split on U+2019")
    print("full escape kept U+2019 inside one string")
    print("checks passed")


if __name__ == "__main__":
    main()
