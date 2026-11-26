#!/usr/bin/env python3
"""本地夹具：技能加载时的注入 shell 不走 PreToolUse。

按 2026-11-26 08:27（Asia/Shanghai）打开的 Hooks reference（hooks.md）
里 PreSkillShellCommand 一节、matcher 规则、`if` 的 Bash 表、退出码表、
Decision control 总表，以及 skills.md 的 Inject dynamic context，在本地走一遍。

不调用 API，不访问网络，不启动 Claude Code，不执行注入命令，不依赖 jq。
`echo 'rm -rf'` 和 `echo $(rm -rf /)` 只作为输入字符串。

这不是 settings 里的 hook，也不是 Claude Code 运行时。
夹具按 v2.1.332 的契约模拟。不探测本机 Claude Code 版本。
2.1.331 及更早会弹出 Unknown hook event，并在不调用这只钩子的情况下跑注入命令。
那一条写在 README，不做成运行时分支。

页上没写成可执行结果的格子 simulated=0，不算裁决：
exit 2 同时带 continue:false 时，这只事件谁先算；
hookEventName 既不是 PreToolUse 也不是 PreSkillShellCommand 时，JSON 还认不认；
技能 frontmatter 钩子在父会话第二次加载时打不打得到自己的注入命令；
子代理定义里的钩子在非 fork 加载时打不打得到；
PowerShell 的 if 没有和 Bash 那张表对等的匹配表；
Remote Control 连着时，占位符字符串本身怎么拼；
顶层 decision 不是 block 的其他取值。
"""

from __future__ import annotations

import json
import re
import sys

FAILS: list[str] = []
EXECUTED: list[str] = []
NETWORK = 0

TRANSCRIPT = "/Users/my-project/.claude/projects/demo/transcript.jsonl"
TRANSCRIPT_TOOL_IDS: set[str] = set()

VERSION_CONTRACT = "2.1.332"
RUNTIME_VERSION_PROBE = 0

EXACT_MATCHER_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ,|"
)
ACCEPTED_EVENT_NAMES = frozenset({"PreToolUse", "PreSkillShellCommand"})
POLICY_TEXT = "[shell command execution disabled by policy]"


def expect(name: str, actual: dict, expected: dict) -> None:
    bad = []
    for key, want in expected.items():
        got = actual.get(key, "<missing>")
        if got != want:
            bad.append(f"{key}: got {got!r} want {want!r}")
    if bad:
        FAILS.append(name + " | " + "; ".join(bad))
    shown = " ".join(
        f"{key}={str(actual.get(key, '<missing>')).replace(chr(10), '\\n')}"
        for key in expected
    )
    print(f"case={name} {shown}")


def build_payload(command: dict, meta: dict) -> dict:
    """stdin 形状。tool_use_id 不写入 transcript，也不对应一次工具调用。"""
    return {
        "session_id": "abc123",
        "transcript_path": TRANSCRIPT,
        "cwd": "/Users/my-project",
        "permission_mode": meta["permission_mode"],
        "hook_event_name": "PreSkillShellCommand",
        "tool_name": command["tool_name"],
        "tool_input": {"command": command["command"]},
        "tool_use_id": command["tool_use_id"],
        "command_name": meta["command_name"],
        "command_source": meta["command_source"],
        "invoked_by": meta["invoked_by"],
    }


def matcher_hits(matcher: str | None, tool_name: str) -> bool:
    """省略、空字符串、* 打全部。只含字母数字和 , | 时做精确列表。其余按未锚定正则。"""
    if matcher is None or matcher in ("", "*"):
        return True
    if all(char in EXACT_MATCHER_CHARS for char in matcher):
        parts = [part.strip() for part in matcher.replace(",", "|").split("|")]
        parts = [part for part in parts if part]
        return tool_name in parts
    return re.search(matcher, tool_name) is not None


def _strip_assignments(command: str) -> str:
    return re.sub(r"^(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)+", "", command)


def _has_substitution(command: str) -> bool:
    if "$(" in command or "`" in command:
        return True
    return re.search(r"\$[A-Za-z_][A-Za-z0-9_]*", command) is not None


def _unsplittable(command: str) -> bool:
    """页上说拆不开就让钩子跑。夹具只把单引号不成对当成拆不开。"""
    return command.count("'") % 2 == 1


def _pieces(command: str) -> list[str]:
    """Bash if 表里出现过的切法：去掉前导赋值，按 && 分，再取出 $() 和反引号。"""
    command = _strip_assignments(command)
    found: list[str] = []
    for part in command.split("&&"):
        part = part.strip()
        if not part:
            continue
        found.append(part)
        found.extend(piece.strip() for piece in re.findall(r"\$\(([^)]*)\)", part))
        found.extend(piece.strip() for piece in re.findall(r"`([^`]*)`", part))
    return [piece for piece in found if piece]


def _more_than_command_name(inner: str) -> bool:
    body = inner[:-2].strip() if inner.endswith(" *") else inner.strip()
    return len(body.split()) > 1


def _sub_matches(inner: str, sub: str) -> bool:
    if not inner.endswith(" *"):
        return False
    prefix = inner[:-2].strip()
    return sub == prefix or sub.startswith(prefix + " ")


class NotStated(Exception):
    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


def if_matches(if_rule: str | None, tool_name: str, command: str) -> bool:
    """if 在这只事件上会求值。不匹配则钩子不跑。

    Bash 只覆盖「How if patterns match Bash commands」那五行，外加拆不开就跑。
    PowerShell(...) 没有对等的表，调用方应把它记成未模拟。
    """
    if if_rule is None:
        return True
    if if_rule.startswith("PowerShell("):
        raise NotStated("powershell_if")
    match = re.fullmatch(r"([A-Za-z]+)\((.*)\)", if_rule)
    if not match:
        raise NotStated("if_shape")
    tool, inner = match.group(1), match.group(2)
    if tool != tool_name:
        return False
    if tool != "Bash":
        raise NotStated("non_bash_if")
    if _unsplittable(command):
        return True
    if _has_substitution(command) and _more_than_command_name(inner):
        return True
    return any(_sub_matches(inner, piece) for piece in _pieces(command))


def extract_injected(body: str) -> dict:
    """行内 !`cmd` 只认行首或空白之后。KEY=!`cmd` 留下原文。

    ```! 围栏整段当成一条命令字符串。页上没写要不要按行拆开。
    """
    fences: list[str] = []
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"```!\n(.*?)```", body, re.S):
        fences.append(match.group(1).strip("\n"))
        spans.append((match.start(), match.end()))

    def covered(index: int) -> bool:
        return any(start <= index < end for start, end in spans)

    inlines: list[str] = []
    literals: list[str] = []
    index = 0
    for line in body.splitlines(keepends=True):
        if not covered(index):
            for match in re.finditer(r"!`([^`]*)`", line):
                before = line[: match.start()]
                if before == "" or before[-1].isspace():
                    inlines.append(match.group(1))
                else:
                    literals.append(line.strip())
        index += len(line)
    return {"inlines": inlines, "fences": fences, "literals": literals}


def substitute_once(body: str, output: str) -> str:
    """替换只做一轮。输出里再出现 !`...` 不会被这只函数展开。"""

    def replacer(match: re.Match[str], line: str) -> str:
        before = line[: match.start()]
        if before == "" or before[-1].isspace():
            return output
        return match.group(0)

    fences: list[tuple[int, int]] = []
    for match in re.finditer(r"```!\n(.*?)```", body, re.S):
        fences.append((match.start(), match.end()))

    def covered(index: int) -> bool:
        return any(start <= index < end for start, end in fences)

    chunks: list[str] = []
    index = 0
    for line in body.splitlines(keepends=True):
        if covered(index):
            chunks.append(line)
        else:
            chunks.append(
                re.sub(
                    r"!`([^`]*)`",
                    lambda match, current=line: replacer(match, current),
                    line,
                )
            )
        index += len(line)
    text = "".join(chunks)
    text = re.sub(r"```!\n(.*?)```", output, text, flags=re.S)
    return text


def _specific(stdout: dict) -> dict:
    value = stdout.get("hookSpecificOutput")
    if isinstance(value, dict):
        return value
    return {}


def schema_state(stdout: dict) -> str:
    """hookSpecificOutput 必须带 hookEventName。

    这只事件允许把名字留成 PreToolUse，也可以写成 PreSkillShellCommand。
    其他名字页上没有写成认还是不认。
    """
    if "hookSpecificOutput" not in stdout:
        return "ok"
    value = stdout["hookSpecificOutput"]
    if not isinstance(value, dict) or "hookEventName" not in value:
        return "invalid"
    if value["hookEventName"] not in ACCEPTED_EVENT_NAMES:
        return "not_stated"
    return "ok"


def parse_stdout(stdout: object) -> tuple[str, dict | None]:
    if stdout is None:
        return "empty", None
    if isinstance(stdout, dict):
        return "json", stdout
    if not isinstance(stdout, str):
        return "invalid", None
    text = stdout.strip()
    if text == "":
        return "empty", None
    if not (text.startswith("{") and text.endswith("}")):
        return "plain", None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return "invalid", None
    if not isinstance(value, dict):
        return "plain", None
    return "json", value


def classify_stdout(stdout: dict | None) -> dict:
    """exit 0 时，PreSkillShellCommand 的 JSON 只能拦，不能批准或改写。

    ask、defer、任何 updatedInput 都按 deny。
    hookEventName 留成 PreToolUse 时，这份 JSON 仍然是这只事件的决定。
    continue:false 停掉整次技能调用，不是只跳过一条命令。
    """
    if not stdout:
        return {"effect": "no_decision", "reason": "", "rewritten": 0, "asked": 0, "deferred": 0}
    state = schema_state(stdout)
    if state == "invalid":
        return {"effect": "invalid", "reason": "", "rewritten": 0, "asked": 0, "deferred": 0}
    if state == "not_stated":
        return {"effect": "not_stated", "why": "hook_event_name", "reason": ""}
    if stdout.get("continue") is False:
        return {
            "effect": "stop",
            "stop_reason": stdout.get("stopReason") or "",
            "reason": "",
            "rewritten": 0,
            "asked": 0,
            "deferred": 0,
        }
    decision = stdout.get("decision")
    if decision not in (None, "block"):
        return {"effect": "not_stated", "why": "decision_value", "reason": ""}
    spec = _specific(stdout)
    permission = spec.get("permissionDecision")
    updated = "updatedInput" in spec
    if decision == "block" or permission in ("deny", "ask", "defer") or updated:
        if decision == "block" and permission is None and not updated:
            reason = stdout.get("reason") or ""
        else:
            reason = spec.get("permissionDecisionReason") or ""
        return {
            "effect": "block",
            "reason": reason,
            "rewritten": 0,
            "asked": 0,
            "deferred": 0,
            "updated": int(updated),
        }
    if permission == "allow":
        return {"effect": "allow", "reason": "", "rewritten": 0, "asked": 0, "deferred": 0}
    return {"effect": "no_decision", "reason": "", "rewritten": 0, "asked": 0, "deferred": 0}


def _blocking_json(parsed: dict) -> bool:
    return classify_stdout(parsed).get("effect") == "block"


def hook_in_force(hook: dict, ctx: dict) -> str:
    """settings 和 plugin 会打到注入命令。

    技能自己的 frontmatter：该会话第一次加载、子代理内部、以及 fork，都打不到。
    父会话里更晚的那次加载，页上没有写成打得到。
    fork 技能也不吃子代理定义里的钩子。定义在别的加载里打不打得到，页上没写。
    """
    location = hook.get("location", "settings")
    if location in ("settings", "plugin"):
        return "yes"
    if location == "skill_frontmatter":
        if ctx["first_load"] or ctx["inside_subagent"] or ctx["forked"]:
            return "no"
        return "not_stated"
    if location == "subagent_definition":
        if ctx["forked"]:
            return "no"
        return "not_stated"
    return "not_stated"


def consult(hook: dict, command: dict, ctx: dict, meta: dict) -> dict:
    tool_name = command["tool_name"]
    if "PreSkillShellCommand" not in hook.get("events", []):
        return {"ran": 0, "effect": "skip", "ignored_event": 1}
    if not matcher_hits(hook.get("matcher"), tool_name):
        return {"ran": 0, "effect": "skip"}
    hook_type = hook.get("type", "command")
    if hook_type in ("prompt", "agent"):
        return {"ran": 0, "effect": "type_block", "hook_type": hook_type}
    try:
        matched = if_matches(hook.get("if"), tool_name, command["command"])
    except NotStated as exc:
        return {"ran": 0, "effect": "not_stated", "why": exc.why}
    if not matched:
        return {"ran": 0, "effect": "skip"}
    if hook.get("async"):
        return {"ran": 0, "effect": "async_noop"}

    on_failure = hook.get("on_failure")
    windows_fail_closed = bool(
        ctx["windows_no_git_bash"]
        and hook.get("shell_form")
        and on_failure is None
        and hook_type == "command"
    )
    failure_blocks = on_failure == "block" or windows_fail_closed

    def failed(why: str) -> dict:
        if failure_blocks or (hook.get("timed_out") and ctx["code_mode_already_ran_code"]):
            return {"ran": 1, "effect": "failure_block", "why": why}
        return {"ran": 1, "effect": "ran_anyway", "why": why}

    if hook.get("timed_out"):
        return failed("timeout")
    if hook.get("failed_to_start"):
        return failed("start")

    if "fn" in hook:
        exit_code, stdout, stderr = hook["fn"](build_payload(command, meta))
        stderr = stderr or ""
    else:
        exit_code = hook.get("exit", 0)
        stdout = hook.get("stdout")
        stderr = hook.get("stderr") or ""

    kind, parsed = parse_stdout(stdout)
    if kind == "json" and parsed is not None and schema_state(parsed) == "invalid":
        kind = "invalid"
    if kind == "json" and parsed is not None and schema_state(parsed) == "not_stated":
        return {"ran": 1, "effect": "not_stated", "why": "hook_event_name"}

    if exit_code == 2 and kind == "json" and parsed is not None and parsed.get("continue") is False:
        return {"ran": 1, "effect": "not_stated", "why": "exit2_and_continue"}

    if exit_code == 2:
        if kind == "json" and parsed is not None and _blocking_json(parsed):
            decision = classify_stdout(parsed)
            return {
                "ran": 1,
                "effect": "block",
                "reason": decision.get("reason") or "",
                "via": "exit2_json",
                "rewritten": 0,
                "asked": 0,
                "deferred": 0,
            }
        return {
            "ran": 1,
            "effect": "block",
            "reason": stderr,
            "via": "exit2",
            "rewritten": 0,
            "asked": 0,
            "deferred": 0,
        }

    if exit_code == 0:
        if kind in ("empty", "plain"):
            return {"ran": 1, "effect": "no_decision"}
        if kind != "json" or parsed is None:
            return failed("invalid_json")
        decision = classify_stdout(parsed)
        decision["ran"] = 1
        return decision

    if failure_blocks:
        return failed(f"exit_{exit_code}")
    if kind == "json" and parsed is not None:
        decision = classify_stdout(parsed)
        if decision.get("effect") == "invalid":
            return failed(f"exit_{exit_code}")
        decision["ran"] = 1
        decision["ignored_exit"] = exit_code
        return decision
    return failed(f"exit_{exit_code}")


def _not_stated(why: str) -> dict:
    return {
        "simulated": 0,
        "why": why,
        "skill_loaded": 0,
        "invocation_failed": 0,
        "stop_message": "",
        "permission_abort": 0,
        "permission_error": "",
        "hook_calls": 0,
        "executed": 0,
        "network": NETWORK,
        "contract_runs": 0,
        "blocked": 0,
        "ran_anyway": 0,
        "placeholder": "",
        "terminal": "",
        "asked": 0,
        "deferred": 0,
        "rewritten": 0,
        "user_sees_reason": 0,
        "claude_sees_reason": 0,
        "debug_log": 0,
        "instruction": 0,
        "later_event": "",
        "hook_ran": 0,
        "payload_event": "",
        "payload_tool": "",
        "payload_command": "",
        "payload_mode": "",
        "payload_name": "",
        "payload_source": "",
        "payload_invoked_by": "",
        "payload_tool_use_id": "",
        "transcript_has_id": 0,
        "cmd1_contract_runs": 0,
        "cmd1_blocked": 0,
        "policy_text": "",
        "bash_missing": 0,
    }


def _abort(message: str, exact: int) -> dict:
    result = _not_stated("")
    result.update(
        {
            "simulated": 1,
            "why": "",
            "skill_loaded": 0,
            "invocation_failed": 1,
            "permission_abort": 1,
            "permission_error": message,
            "permission_error_exact": exact,
            "executed": 0,
        }
    )
    return result


def simulate(
    commands: list[dict],
    hooks: list[dict],
    *,
    command_name: str = "hook-test",
    permission_mode: str = "default",
    invoked_by: str = "user",
    command_source: str = "projectSettings",
    first_load: bool = True,
    inside_subagent: bool = False,
    forked: bool = False,
    forked_sets_agent: bool = False,
    remote_control: bool = False,
    code_mode_already_ran_code: bool = False,
    disable_skill_shell: bool = False,
    policy_affects_source: bool = True,
    mcp_skill: bool = False,
    shell_pref: str = "bash",
    bash_available: bool = True,
    shell_tool_available: bool = True,
    windows_no_git_bash: bool = False,
) -> dict:
    meta = {
        "command_name": command_name,
        "permission_mode": permission_mode,
        "invoked_by": invoked_by,
        "command_source": command_source,
    }
    ctx = {
        "first_load": first_load,
        "inside_subagent": inside_subagent,
        "forked": forked,
        "remote_control": remote_control,
        "code_mode_already_ran_code": code_mode_already_ran_code,
        "windows_no_git_bash": windows_no_git_bash,
    }
    if mcp_skill:
        result = _not_stated("")
        result.update(
            {
                "simulated": 1,
                "skill_loaded": 1,
                "mcp_bang_ran": 0,
                "not_this_gate": 1,
            }
        )
        return result
    if shell_pref == "bash" and not bash_available:
        message = (
            f"Skill {command_name} requires bash (`shell: bash` in frontmatter) "
            "but Git Bash was not found"
        )
        result = _abort(message, 1)
        result["bash_missing"] = 1
        result["permission_abort"] = 0
        return result
    if disable_skill_shell and policy_affects_source:
        result = _not_stated("")
        result.update(
            {
                "simulated": 1,
                "skill_loaded": 1,
                "policy_text": POLICY_TEXT,
                "hook_calls": 0,
                "executed": 0,
            }
        )
        return result
    if not shell_tool_available and permission_mode == "auto":
        if any(item["permission"] != "allow" for item in commands):
            return _abort("", 0)

    for item in commands:
        if item["permission"] == "deny":
            pattern = item.get("pattern") or item["command"]
            return _abort(
                f'Shell command permission check failed for pattern "{pattern}"',
                1,
            )
    if permission_mode != "auto" or forked_sets_agent:
        if any(item["permission"] != "allow" for item in commands):
            return _abort("", 0)

    for hook in hooks:
        if hook_in_force(hook, ctx) == "not_stated":
            return _not_stated("location")

    reaching = []
    deferred = []
    for item in commands:
        if permission_mode == "auto" and item["permission"] == "ask":
            deferred.append(item)
        else:
            reaching.append(item)

    per_command: list[dict] = []
    hook_calls = 0
    sample: dict | None = None
    stop_reason = None
    preskill_ignored = 0

    for item in reaching:
        effects = []
        for hook in hooks:
            if hook_in_force(hook, ctx) != "yes":
                continue
            if "PreSkillShellCommand" not in hook.get("events", []):
                preskill_ignored += 1
                continue
            outcome = consult(hook, item, ctx, meta)
            if outcome.get("effect") == "not_stated":
                return _not_stated(outcome.get("why") or "not_stated")
            if outcome.get("ran"):
                hook_calls += 1
                if sample is None:
                    sample = build_payload(item, meta)
            effects.append(outcome)
            if outcome.get("effect") == "stop" and stop_reason is None:
                stop_reason = outcome.get("stop_reason") or ""
        per_command.append({"item": item, "effects": effects, "deferred": 0})

    for item in deferred:
        per_command.append({"item": item, "effects": [], "deferred": 1})

    if stop_reason is not None:
        result = _not_stated("")
        result.update(
            {
                "simulated": 1,
                "skill_loaded": 0,
                "invocation_failed": 1,
                "stop_message": f"Operation stopped by hook: {stop_reason}",
                "hook_calls": hook_calls,
                "executed": 0,
                "contract_runs": 0,
                "cmd1_contract_runs": 0,
                "later_event": "",
                "instruction": 0,
            }
        )
        if sample:
            _fill_payload(result, sample)
        return result

    rendered = []
    for entry in per_command:
        item = entry["item"]
        if entry["deferred"]:
            rendered.append(
                {
                    "contract_runs": 0,
                    "blocked": 0,
                    "ran_anyway": 0,
                    "placeholder": "",
                    "terminal": "",
                    "asked": 0,
                    "deferred": 1,
                    "rewritten": 0,
                    "user_sees_reason": 0,
                    "claude_sees_reason": 0,
                    "debug_log": 0,
                    "hook_ran": 0,
                    "executed": 0,
                }
            )
            continue
        blocks = [item_effect for item_effect in entry["effects"] if item_effect.get("effect") in ("block", "type_block", "failure_block")]
        anyway = [item_effect for item_effect in entry["effects"] if item_effect.get("effect") == "ran_anyway"]
        ran = sum(1 for item_effect in entry["effects"] if item_effect.get("ran"))
        view = {
            "contract_runs": 0,
            "blocked": 0,
            "ran_anyway": 0,
            "placeholder": "",
            "terminal": "",
            "asked": 0,
            "deferred": 0,
            "rewritten": 0,
            "user_sees_reason": 0,
            "claude_sees_reason": 0,
            "debug_log": 0,
            "hook_ran": ran,
            "executed": 0,
        }
        if blocks:
            view["blocked"] = 1
            decision = next((item_effect for item_effect in blocks if item_effect.get("effect") == "block"), None)
            if decision is not None and not remote_control:
                reason = decision.get("reason") or ""
                view["placeholder"] = f"[not run: blocked by hook: {reason}]"
                view["claude_sees_reason"] = 1
                if invoked_by == "user":
                    view["terminal"] = (
                        f"Not run in /{command_name}: {item['command']} "
                        f"(blocked by hook: {reason})"
                    )
                    view["user_sees_reason"] = 1
            elif decision is not None and remote_control:
                view["debug_log"] = 1
                view["user_sees_reason"] = 0
                view["claude_sees_reason"] = 0
            elif any(item_effect.get("effect") == "type_block" for item_effect in blocks):
                view["terminal"] = f"Not run in /{command_name}"
            else:
                view["terminal"] = f"Not run in /{command_name}"
        elif anyway:
            view["contract_runs"] = 1
            view["ran_anyway"] = 1
            if invoked_by == "user":
                view["terminal"] = f"Ran anyway in /{command_name}"
        else:
            view["contract_runs"] = 1
        if item.get("hypothetical_exit") not in (None, 0) and view["contract_runs"]:
            pattern = item["command"]
            result = _abort(f'Shell command failed for pattern "{pattern}"', 1)
            result["permission_abort"] = 0
            result["command_failed"] = 1
            result["hook_calls"] = hook_calls
            result["skill_loaded"] = 0
            return result
        rendered.append(view)

    first = rendered[0] if rendered else {
        "contract_runs": 0,
        "blocked": 0,
        "ran_anyway": 0,
        "placeholder": "",
        "terminal": "",
        "asked": 0,
        "deferred": 0,
        "rewritten": 0,
        "user_sees_reason": 0,
        "claude_sees_reason": 0,
        "debug_log": 0,
        "hook_ran": 0,
    }
    second = rendered[1] if len(rendered) > 1 else {"contract_runs": 0, "blocked": 0}
    result = _not_stated("")
    result.update(
        {
            "simulated": 1,
            "skill_loaded": 1,
            "hook_calls": hook_calls,
            "executed": 0,
            "contract_runs": first["contract_runs"],
            "blocked": first["blocked"],
            "ran_anyway": first["ran_anyway"],
            "placeholder": first["placeholder"],
            "terminal": first["terminal"],
            "asked": 0,
            "deferred": first["deferred"],
            "rewritten": 0,
            "user_sees_reason": first["user_sees_reason"],
            "claude_sees_reason": first["claude_sees_reason"],
            "debug_log": first["debug_log"],
            "hook_ran": first["hook_ran"],
            "instruction": int(bool(deferred)),
            "later_event": "PreToolUse" if deferred else "",
            "cmd1_contract_runs": second.get("contract_runs", 0),
            "cmd1_blocked": second.get("blocked", 0),
            "preskill_ignored": preskill_ignored,
            "command_failed": 0,
            "bash_missing": 0,
            "permission_error_exact": 0,
        }
    )
    if sample:
        _fill_payload(result, sample)
    elif reaching:
        _fill_payload(result, build_payload(reaching[0], meta))
    elif commands:
        _fill_payload(result, build_payload(commands[0], meta))
    return result


def _fill_payload(result: dict, payload: dict) -> None:
    result["payload_event"] = payload["hook_event_name"]
    result["payload_tool"] = payload["tool_name"]
    result["payload_command"] = payload["tool_input"]["command"]
    result["payload_mode"] = payload["permission_mode"]
    result["payload_name"] = payload["command_name"]
    result["payload_source"] = payload["command_source"]
    result["payload_invoked_by"] = payload["invoked_by"]
    result["payload_tool_use_id"] = payload["tool_use_id"]
    result["transcript_has_id"] = int(payload["tool_use_id"] in TRANSCRIPT_TOOL_IDS)


def later_tool_call(command: dict, hooks: list[dict]) -> dict:
    """auto mode 里延后的那次调用走 PreToolUse。只挂在 PreSkillShellCommand 上的脚本不看它。

    这里只模拟「PreToolUse 的 deny / exit 2 会拦住这次工具调用」。
    ask 在 PreToolUse 上会询问。那一页的全文不在这里重写，夹具只记成 prompts。
    """
    ran = 0
    blocked = 0
    for hook in hooks:
        if "PreToolUse" not in hook.get("events", []):
            continue
        if not matcher_hits(hook.get("matcher"), command["tool_name"]):
            continue
        ran += 1
        exit_code = hook.get("exit", 0)
        stdout = hook.get("stdout")
        kind, parsed = parse_stdout(stdout)
        if exit_code == 2:
            blocked = 1
        elif kind == "json" and parsed is not None:
            spec = _specific(parsed)
            if spec.get("permissionDecision") == "deny" or parsed.get("decision") == "block":
                blocked = 1
    return {
        "event": "PreToolUse",
        "hook_ran": ran,
        "tool_blocked": blocked,
        "preskill_event": 0,
        "executed": 0,
        "ask_means": "prompt",
    }


def cmd(
    command: str,
    tool: str = "Bash",
    permission: str = "allow",
    pattern: str = "",
    hypothetical_exit: int | None = None,
    tool_use_id: str | None = None,
) -> dict:
    return {
        "command": command,
        "tool_name": tool,
        "permission": permission,
        "pattern": pattern,
        "hypothetical_exit": hypothetical_exit,
        "tool_use_id": tool_use_id or "inj-not-in-transcript",
    }


def hook(**kwargs: object) -> dict:
    if "if_" in kwargs:
        kwargs["if"] = kwargs.pop("if_")
    if "async_" in kwargs:
        kwargs["async"] = kwargs.pop("async_")
    base: dict = {
        "events": ["PreSkillShellCommand"],
        "matcher": "Bash|PowerShell",
        "if": None,
        "type": "command",
        "async": False,
        "on_failure": None,
        "location": "settings",
        "exit": 0,
        "stdout": None,
        "stderr": "",
        "timed_out": False,
        "failed_to_start": False,
        "shell_form": False,
    }
    base.update(kwargs)
    return base


def deny_json(reason: str, event_name: str = "PreToolUse") -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def block_rm(payload: dict) -> tuple[int, dict | None, str]:
    """官方 block-rm.sh 的字段形状。命令字符串含 rm -rf 就 deny。不执行它。"""
    command = payload["tool_input"]["command"]
    if "rm -rf" in command:
        return 0, deny_json("Destructive command blocked by hook"), ""
    return 0, None, ""


def _run(name: str, commands: list[dict], hooks: list[dict], expected: dict, **kwargs: object) -> None:
    actual = simulate(commands, hooks, **kwargs)
    expect(name, actual, expected)


def main() -> None:
    print(
        "docs=hooks.md,hooks-guide.md,changelog.md,skills.md "
        "access=2026-11-26T08:27:43+08:00 "
        f"contract={VERSION_CONTRACT} runtime_version_probe={RUNTIME_VERSION_PROBE}"
    )

    echo_rm = "echo 'rm -rf'"
    reason = "Destructive command blocked by hook"
    placeholder = f"[not run: blocked by hook: {reason}]"
    not_run = f"Not run in /hook-test: {echo_rm} (blocked by hook: {reason})"

    _run(
        "input_contract",
        [cmd(echo_rm, tool_use_id="inj-echo-rm")],
        [hook(stdout=None)],
        {
            "simulated": 1,
            "payload_event": "PreSkillShellCommand",
            "payload_tool": "Bash",
            "payload_command": echo_rm,
            "payload_mode": "default",
            "payload_name": "hook-test",
            "payload_source": "projectSettings",
            "payload_invoked_by": "user",
            "payload_tool_use_id": "inj-echo-rm",
            "transcript_has_id": 0,
            "executed": 0,
            "network": 0,
            "contract_runs": 1,
        },
        command_source="projectSettings",
        invoked_by="user",
    )

    _run(
        "matcher_bash_skips_powershell",
        [cmd("Get-Location", tool="PowerShell")],
        [hook(matcher="Bash", stdout=deny_json(reason))],
        {"hook_ran": 0, "blocked": 0, "contract_runs": 1, "executed": 0},
    )
    _run(
        "matcher_powershell",
        [cmd("Get-Location", tool="PowerShell")],
        [hook(matcher="PowerShell", stdout=deny_json(reason))],
        {"hook_ran": 1, "blocked": 1, "contract_runs": 0, "executed": 0},
    )
    _run(
        "matcher_bash_or_powershell",
        [cmd(echo_rm)],
        [hook(matcher="Bash|PowerShell", stdout=deny_json(reason))],
        {"blocked": 1, "placeholder": placeholder, "executed": 0},
    )
    _run(
        "matcher_comma",
        [cmd("Get-Location", tool="PowerShell")],
        [hook(matcher="Bash, PowerShell", stdout=deny_json(reason))],
        {"blocked": 1, "executed": 0},
    )
    _run(
        "matcher_omitted",
        [cmd(echo_rm)],
        [hook(matcher=None, stdout=deny_json(reason))],
        {"blocked": 1, "executed": 0},
    )
    _run(
        "matcher_anchored_regex",
        [cmd("Get-Location", tool="PowerShell")],
        [hook(matcher="^Bash$", stdout=deny_json(reason))],
        {"hook_ran": 0, "contract_runs": 1, "executed": 0},
    )
    _run(
        "matcher_anchored_regex_bash",
        [cmd("git status")],
        [hook(matcher="^Bash$", stdout=deny_json("no git"))],
        {"blocked": 1, "executed": 0},
    )

    _run(
        "if_strips_assignment",
        [cmd("FOO=bar git push")],
        [hook(if_="Bash(git *)", stdout=deny_json("no push"))],
        {"hook_ran": 1, "blocked": 1, "executed": 0},
    )
    _run(
        "if_checks_and_subcommand",
        [cmd("npm test && git push")],
        [hook(if_="Bash(git *)", stdout=deny_json("no push"))],
        {"hook_ran": 1, "blocked": 1, "executed": 0},
    )
    _run(
        "if_checks_command_substitution",
        [cmd("echo $(rm -rf /)")],
        [hook(if_="Bash(rm *)", stdout=deny_json(reason))],
        {"hook_ran": 1, "blocked": 1, "contract_runs": 0, "executed": 0, "rewritten": 0},
    )
    _run(
        "if_miss_skips_hook",
        [cmd("echo $(date)")],
        [hook(if_="Bash(rm *)", stdout=deny_json(reason))],
        {"hook_ran": 0, "blocked": 0, "contract_runs": 1, "executed": 0},
    )
    _run(
        "if_longer_pattern_runs_on_substitution",
        [cmd("echo $(date)")],
        [hook(if_="Bash(git push *)", stdout=deny_json("longer"))],
        {"hook_ran": 1, "blocked": 1, "executed": 0},
    )
    _run(
        "if_unsplittable_runs_hook",
        [cmd("echo 'unterminated")],
        [hook(if_="Bash(rm *)", stdout=deny_json(reason))],
        {"hook_ran": 1, "blocked": 1, "executed": 0},
    )
    _run(
        "if_tool_name_must_match",
        [cmd("Remove-Item tmp", tool="PowerShell")],
        [hook(if_="Bash(rm *)", stdout=deny_json(reason))],
        {"hook_ran": 0, "contract_runs": 1, "executed": 0},
    )
    expect(
        "powershell_if_not_stated",
        simulate(
            [cmd("Remove-Item tmp", tool="PowerShell")],
            [hook(if_="PowerShell(Remove-Item *)", stdout=deny_json(reason))],
        ),
        {"simulated": 0, "why": "powershell_if"},
    )

    _run(
        "exit0_no_decision",
        [cmd("git status")],
        [hook(stdout=None)],
        {"contract_runs": 1, "blocked": 0, "ran_anyway": 0, "skill_loaded": 1, "executed": 0},
    )
    _run(
        "plain_text_exit0_is_success",
        [cmd("git status")],
        [hook(stdout="not json")],
        {"contract_runs": 1, "blocked": 0, "ran_anyway": 0, "executed": 0},
    )
    _run(
        "allow_runs_unless_another_blocks",
        [cmd("git status")],
        [
            hook(
                stdout={
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "permissionDecisionReason": "looks fine",
                    }
                }
            )
        ],
        {"contract_runs": 1, "blocked": 0, "executed": 0, "rewritten": 0},
    )
    _run(
        "second_hook_deny_wins",
        [cmd("git status")],
        [
            hook(
                stdout={
                    "hookSpecificOutput": {
                        "hookEventName": "PreSkillShellCommand",
                        "permissionDecision": "allow",
                    }
                }
            ),
            hook(stdout=deny_json("second hook")),
        ],
        {
            "blocked": 1,
            "contract_runs": 0,
            "placeholder": "[not run: blocked by hook: second hook]",
            "executed": 0,
        },
    )
    _run(
        "exit2_stderr",
        [cmd(echo_rm)],
        [hook(exit=2, stderr=reason)],
        {
            "blocked": 1,
            "skill_loaded": 1,
            "placeholder": placeholder,
            "terminal": not_run,
            "contract_runs": 0,
            "executed": 0,
            "user_sees_reason": 1,
            "claude_sees_reason": 1,
        },
    )
    _run(
        "deny_json_keeps_pretooluse_name",
        [cmd(echo_rm)],
        [hook(stdout=deny_json(reason, "PreToolUse"))],
        {
            "blocked": 1,
            "skill_loaded": 1,
            "placeholder": placeholder,
            "terminal": not_run,
            "executed": 0,
            "rewritten": 0,
        },
    )
    _run(
        "deny_json_event_name",
        [cmd(echo_rm)],
        [hook(stdout=deny_json(reason, "PreSkillShellCommand"))],
        {"blocked": 1, "placeholder": placeholder, "executed": 0},
    )
    _run(
        "top_level_decision_block",
        [cmd("git push")],
        [hook(stdout={"decision": "block", "reason": "no push"})],
        {
            "blocked": 1,
            "placeholder": "[not run: blocked by hook: no push]",
            "terminal": "Not run in /hook-test: git push (blocked by hook: no push)",
            "skill_loaded": 1,
            "executed": 0,
        },
    )
    _run(
        "ask_blocked_as_deny",
        [cmd("git push")],
        [
            hook(
                stdout={
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "ask",
                        "permissionDecisionReason": "do not ask",
                    }
                }
            )
        ],
        {
            "blocked": 1,
            "asked": 0,
            "placeholder": "[not run: blocked by hook: do not ask]",
            "executed": 0,
        },
    )
    _run(
        "defer_blocked_as_deny",
        [cmd("git push")],
        [
            hook(
                stdout={
                    "hookSpecificOutput": {
                        "hookEventName": "PreSkillShellCommand",
                        "permissionDecision": "defer",
                        "permissionDecisionReason": "do not defer",
                    }
                }
            )
        ],
        {
            "blocked": 1,
            "deferred": 0,
            "placeholder": "[not run: blocked by hook: do not defer]",
            "executed": 0,
        },
    )
    _run(
        "updated_input_blocked_not_rewritten",
        [cmd("git push")],
        [
            hook(
                stdout={
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                        "updatedInput": {"command": "echo safe"},
                        "permissionDecisionReason": "no rewrite",
                    }
                }
            )
        ],
        {
            "blocked": 1,
            "rewritten": 0,
            "placeholder": "[not run: blocked by hook: no rewrite]",
            "payload_command": "git push",
            "executed": 0,
        },
    )
    _run(
        "updated_input_alone",
        [cmd("git push")],
        [
            hook(
                stdout={
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "updatedInput": {"command": "echo safe"},
                    }
                }
            )
        ],
        {
            "blocked": 1,
            "rewritten": 0,
            "placeholder": "[not run: blocked by hook: ]",
            "executed": 0,
        },
    )
    _run(
        "exit2_uses_json_reason",
        [cmd("git push")],
        [hook(exit=2, stderr="from stderr", stdout=deny_json("from json"))],
        {"blocked": 1, "placeholder": "[not run: blocked by hook: from json]", "executed": 0},
    )
    _run(
        "exit2_allow_still_blocks",
        [cmd("git push")],
        [
            hook(
                exit=2,
                stderr="still blocked",
                stdout={
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                    }
                },
            )
        ],
        {
            "blocked": 1,
            "placeholder": "[not run: blocked by hook: still blocked]",
            "executed": 0,
        },
    )
    _run(
        "missing_hook_event_name_exit0",
        [cmd("git status")],
        [
            hook(
                stdout={
                    "hookSpecificOutput": {
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "unnamed",
                    }
                }
            )
        ],
        {"blocked": 0, "ran_anyway": 1, "contract_runs": 1, "terminal": "Ran anyway in /hook-test"},
    )
    _run(
        "missing_hook_event_name_exit2",
        [cmd("git status")],
        [
            hook(
                exit=2,
                stderr="stderr wins",
                stdout={"hookSpecificOutput": {"permissionDecision": "allow"}},
            )
        ],
        {"blocked": 1, "placeholder": "[not run: blocked by hook: stderr wins]", "executed": 0},
    )
    expect(
        "other_hook_event_name_not_stated",
        simulate(
            [cmd("git status")],
            [
                hook(
                    stdout={
                        "hookSpecificOutput": {
                            "hookEventName": "MessageDisplay",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": "nope",
                        }
                    }
                )
            ],
        ),
        {"simulated": 0, "why": "hook_event_name"},
    )
    expect(
        "exit2_and_continue_not_stated",
        simulate(
            [cmd("git status")],
            [hook(exit=2, stderr="x", stdout={"continue": False, "stopReason": "stop"})],
        ),
        {"simulated": 0, "why": "exit2_and_continue"},
    )
    _run(
        "continue_false_stops_every_command",
        [cmd("git status"), cmd("git diff")],
        [
            hook(stdout=None),
            hook(stdout={"continue": False, "stopReason": "stop now"}),
        ],
        {
            "simulated": 1,
            "invocation_failed": 1,
            "skill_loaded": 0,
            "stop_message": "Operation stopped by hook: stop now",
            "contract_runs": 0,
            "cmd1_contract_runs": 0,
            "executed": 0,
            "instruction": 0,
        },
    )
    _run(
        "per_command_deny_still_loads",
        [cmd("git push"), cmd("git status")],
        [hook(if_="Bash(git push *)", stdout=deny_json("no push"))],
        {
            "blocked": 1,
            "skill_loaded": 1,
            "contract_runs": 0,
            "cmd1_contract_runs": 1,
            "cmd1_blocked": 0,
            "placeholder": "[not run: blocked by hook: no push]",
            "executed": 0,
        },
    )

    _run(
        "exit1_without_json_runs",
        [cmd("git status")],
        [hook(exit=1, stdout=None)],
        {
            "contract_runs": 1,
            "ran_anyway": 1,
            "blocked": 0,
            "terminal": "Ran anyway in /hook-test",
            "skill_loaded": 1,
            "executed": 0,
        },
    )
    _run(
        "exit1_deny_json_fields_decide",
        [cmd("git push")],
        [hook(exit=1, stdout=deny_json("fields decide"))],
        {
            "blocked": 1,
            "ran_anyway": 0,
            "placeholder": "[not run: blocked by hook: fields decide]",
            "executed": 0,
        },
    )
    _run(
        "onfailure_block",
        [cmd("git status")],
        [hook(exit=1, stdout=None, on_failure="block")],
        {"blocked": 1, "ran_anyway": 0, "contract_runs": 0, "skill_loaded": 1, "executed": 0},
    )
    _run(
        "timeout_runs",
        [cmd("git status")],
        [hook(timed_out=True, stdout=deny_json("ignored"))],
        {"contract_runs": 1, "ran_anyway": 1, "terminal": "Ran anyway in /hook-test", "executed": 0},
    )
    _run(
        "timeout_onfailure_block",
        [cmd("git status")],
        [hook(timed_out=True, on_failure="block")],
        {"blocked": 1, "ran_anyway": 0, "contract_runs": 0, "executed": 0},
    )
    _run(
        "timeout_code_mode_blocks",
        [cmd("git status")],
        [hook(timed_out=True)],
        {"blocked": 1, "ran_anyway": 0, "contract_runs": 0, "skill_loaded": 1, "executed": 0},
        code_mode_already_ran_code=True,
    )
    _run(
        "windows_shell_form_failure_blocks",
        [cmd("git status")],
        [hook(exit=1, shell_form=True, stdout={"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}})],
        {"blocked": 1, "contract_runs": 0, "executed": 0},
        windows_no_git_bash=True,
    )
    _run(
        "windows_onfailure_continue_uses_fields",
        [cmd("git status")],
        [
            hook(
                exit=1,
                shell_form=True,
                on_failure="continue",
                stdout={
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "allow",
                    }
                },
            )
        ],
        {"contract_runs": 1, "blocked": 0, "executed": 0},
        windows_no_git_bash=True,
    )

    _run(
        "pretooluse_only_misses_injection",
        [cmd(echo_rm)],
        [hook(events=["PreToolUse"], stdout=deny_json(reason))],
        {
            "hook_calls": 0,
            "hook_ran": 0,
            "blocked": 0,
            "contract_runs": 1,
            "preskill_ignored": 1,
            "executed": 0,
        },
    )
    _run(
        "shared_script_on_both_events",
        [cmd(echo_rm)],
        [hook(events=["PreToolUse", "PreSkillShellCommand"], fn=block_rm)],
        {
            "blocked": 1,
            "placeholder": placeholder,
            "terminal": not_run,
            "skill_loaded": 1,
            "executed": 0,
        },
    )
    later = later_tool_call(
        cmd("git push"),
        [hook(events=["PreToolUse", "PreSkillShellCommand"], stdout=deny_json("tool deny"))],
    )
    expect(
        "later_tool_call_is_pretooluse",
        later,
        {"event": "PreToolUse", "hook_ran": 1, "tool_blocked": 1, "preskill_event": 0, "executed": 0, "ask_means": "prompt"},
    )
    missed = later_tool_call(
        cmd("git push"),
        [hook(events=["PreSkillShellCommand"], stdout=deny_json("only skill"))],
    )
    expect(
        "preskill_only_misses_later_tool_call",
        missed,
        {"event": "PreToolUse", "hook_ran": 0, "tool_blocked": 0, "executed": 0},
    )

    _run(
        "deny_rule_aborts_before_hook",
        [cmd("git push", permission="deny", pattern="git push *"), cmd("git status")],
        [hook(stdout=deny_json("should not run"))],
        {
            "permission_abort": 1,
            "skill_loaded": 0,
            "hook_calls": 0,
            "permission_error": 'Shell command permission check failed for pattern "git push *"',
            "permission_error_exact": 1,
            "executed": 0,
        },
    )
    _run(
        "ask_outside_auto_aborts",
        [cmd("git push", permission="ask")],
        [hook(stdout=deny_json("should not run"))],
        {
            "permission_abort": 1,
            "skill_loaded": 0,
            "hook_calls": 0,
            "permission_error_exact": 0,
            "executed": 0,
        },
    )
    _run(
        "auto_ask_defers_to_pretooluse",
        [cmd("git push", permission="ask")],
        [hook(events=["PreToolUse", "PreSkillShellCommand"], stdout=deny_json("load"))],
        {
            "hook_calls": 0,
            "deferred": 1,
            "instruction": 1,
            "later_event": "PreToolUse",
            "skill_loaded": 1,
            "contract_runs": 0,
            "blocked": 0,
            "executed": 0,
        },
        permission_mode="auto",
    )
    _run(
        "auto_allow_still_hits_preskill",
        [cmd("git status", permission="allow")],
        [hook(stdout=deny_json("still here"))],
        {"hook_ran": 1, "blocked": 1, "later_event": "", "executed": 0},
        permission_mode="auto",
    )
    _run(
        "auto_fork_agent_ask_aborts",
        [cmd("git push", permission="ask")],
        [hook(stdout=deny_json("no"))],
        {"permission_abort": 1, "hook_calls": 0, "skill_loaded": 0, "executed": 0},
        permission_mode="auto",
        forked_sets_agent=True,
    )
    _run(
        "bypass_permissions_still_runs_hook",
        [cmd(echo_rm)],
        [hook(fn=block_rm)],
        {
            "blocked": 1,
            "payload_mode": "bypassPermissions",
            "placeholder": placeholder,
            "executed": 0,
        },
        permission_mode="bypassPermissions",
    )

    _run(
        "frontmatter_first_load_misses",
        [cmd(echo_rm)],
        [hook(location="skill_frontmatter", fn=block_rm)],
        {"hook_ran": 0, "hook_calls": 0, "contract_runs": 1, "blocked": 0, "executed": 0},
        first_load=True,
    )
    _run(
        "frontmatter_inside_subagent_misses",
        [cmd(echo_rm)],
        [hook(location="skill_frontmatter", fn=block_rm)],
        {"hook_calls": 0, "contract_runs": 1, "executed": 0},
        first_load=False,
        inside_subagent=True,
    )
    _run(
        "frontmatter_fork_misses",
        [cmd(echo_rm)],
        [hook(location="skill_frontmatter", fn=block_rm)],
        {"hook_calls": 0, "contract_runs": 1, "executed": 0},
        first_load=False,
        forked=True,
    )
    _run(
        "subagent_definition_fork_misses",
        [cmd(echo_rm)],
        [hook(location="subagent_definition", fn=block_rm)],
        {"hook_calls": 0, "contract_runs": 1, "executed": 0},
        forked=True,
    )
    expect(
        "later_frontmatter_not_stated",
        simulate(
            [cmd(echo_rm)],
            [hook(location="skill_frontmatter", fn=block_rm)],
            first_load=False,
        ),
        {"simulated": 0, "why": "location"},
    )
    expect(
        "subagent_definition_parent_not_stated",
        simulate(
            [cmd(echo_rm)],
            [hook(location="subagent_definition", fn=block_rm)],
            forked=False,
        ),
        {"simulated": 0, "why": "location"},
    )
    _run(
        "settings_hook_on_fork_still_blocks",
        [cmd(echo_rm)],
        [hook(location="settings", fn=block_rm)],
        {"blocked": 1, "placeholder": placeholder, "executed": 0},
        forked=True,
        first_load=True,
    )
    _run(
        "plugin_hook_on_first_load_blocks",
        [cmd(echo_rm)],
        [hook(location="plugin", fn=block_rm)],
        {"blocked": 1, "executed": 0},
        first_load=True,
    )

    _run(
        "prompt_hook_blocks_without_running",
        [cmd("git push")],
        [hook(type="prompt", matcher="Bash")],
        {"blocked": 1, "hook_ran": 0, "asked": 0, "skill_loaded": 1, "contract_runs": 0, "executed": 0},
    )
    _run(
        "agent_hook_blocks_without_running",
        [cmd("git push")],
        [hook(type="agent")],
        {"blocked": 1, "hook_ran": 0, "skill_loaded": 1, "executed": 0},
    )
    _run(
        "prompt_hook_matcher_miss",
        [cmd("git push")],
        [hook(type="prompt", matcher="Edit")],
        {"blocked": 0, "contract_runs": 1, "executed": 0},
    )
    _run(
        "async_cannot_block",
        [cmd("git push")],
        [hook(async_=True, stdout=deny_json("async deny"), exit=2)],
        {"blocked": 0, "contract_runs": 1, "hook_ran": 0, "executed": 0},
    )
    _run(
        "async_continue_false_has_no_effect",
        [cmd("git status")],
        [hook(async_=True, stdout={"continue": False, "stopReason": "no"})],
        {"invocation_failed": 0, "skill_loaded": 1, "contract_runs": 1, "executed": 0},
    )
    _run(
        "http_json_can_block",
        [cmd("git push")],
        [hook(type="http", stdout=deny_json("http deny"))],
        {"blocked": 1, "placeholder": "[not run: blocked by hook: http deny]", "network": 0, "executed": 0},
    )
    _run(
        "mcp_tool_json_can_block",
        [cmd("git push")],
        [hook(type="mcp_tool", stdout=deny_json("mcp deny", "PreSkillShellCommand"))],
        {"blocked": 1, "network": 0, "executed": 0},
    )
    _run(
        "remote_control_hides_reason",
        [cmd(echo_rm)],
        [hook(fn=block_rm)],
        {
            "blocked": 1,
            "user_sees_reason": 0,
            "claude_sees_reason": 0,
            "debug_log": 1,
            "placeholder": "",
            "skill_loaded": 1,
            "executed": 0,
        },
        remote_control=True,
    )
    _run(
        "official_hook_test",
        [cmd(echo_rm, tool_use_id="inj-hook-test")],
        [hook(matcher="Bash|PowerShell", on_failure="block", fn=block_rm)],
        {
            "blocked": 1,
            "skill_loaded": 1,
            "executed": 0,
            "placeholder": placeholder,
            "terminal": not_run,
            "payload_command": echo_rm,
            "transcript_has_id": 0,
            "payload_tool": "Bash",
        },
    )

    extracted = extract_injected(
        "\n".join(
            [
                "!`echo 'rm -rf'`",
                "  !`git status`",
                "KEY=!`echo hidden`",
                "## Environment",
                "```!",
                "node --version",
                "git status --short",
                "```",
                "",
            ]
        )
    )
    expect(
        "extract_inline_and_fence",
        {
            "inlines": "|".join(extracted["inlines"]),
            "literals": "|".join(extracted["literals"]),
            "fence_lines": extracted["fences"][0] if extracted["fences"] else "",
            "fence_count": len(extracted["fences"]),
        },
        {
            "inlines": "echo 'rm -rf'|git status",
            "literals": "KEY=!`echo hidden`",
            "fence_lines": "node --version\ngit status --short",
            "fence_count": 1,
        },
    )
    once = substitute_once("Before !`echo marker`\n", "see !`echo nested`")
    again = extract_injected(once)
    expect(
        "substitute_once",
        {
            "text": once,
            "rescan": 0,
            "would_match_if_rescanned": "|".join(again["inlines"]),
            "executed": len(EXECUTED),
        },
        {
            "text": "Before see !`echo nested`\n",
            "rescan": 0,
            "would_match_if_rescanned": "echo nested",
            "executed": 0,
        },
    )
    _run(
        "disable_skill_shell_execution",
        [cmd(echo_rm)],
        [hook(fn=block_rm)],
        {
            "skill_loaded": 1,
            "hook_calls": 0,
            "policy_text": POLICY_TEXT,
            "blocked": 0,
            "executed": 0,
        },
        disable_skill_shell=True,
        policy_affects_source=True,
    )
    _run(
        "policy_does_not_cover_exempt_source",
        [cmd(echo_rm)],
        [hook(fn=block_rm)],
        {"hook_ran": 1, "blocked": 1, "policy_text": "", "executed": 0},
        disable_skill_shell=True,
        policy_affects_source=False,
    )
    mcp = simulate([cmd(echo_rm)], [hook(fn=block_rm)], mcp_skill=True)
    expect(
        "mcp_skill_bang_does_not_run",
        mcp,
        {"skill_loaded": 1, "hook_calls": 0, "mcp_bang_ran": 0, "not_this_gate": 1, "executed": 0},
    )
    missing = simulate([cmd("git status")], [hook(fn=block_rm)], bash_available=False)
    expect(
        "bash_missing_aborts_before_hook",
        missing,
        {
            "bash_missing": 1,
            "hook_calls": 0,
            "skill_loaded": 0,
            "permission_error": "Skill hook-test requires bash (`shell: bash` in frontmatter) but Git Bash was not found",
            "executed": 0,
        },
    )
    _run(
        "command_failure_aborts_invocation",
        [cmd("false", hypothetical_exit=1)],
        [hook(stdout=None)],
        {
            "command_failed": 1,
            "skill_loaded": 0,
            "permission_error": 'Shell command failed for pattern "false"',
            "placeholder": "",
            "executed": 0,
        },
    )
    expect(
        "search_exit_1_carveout_not_simulated",
        {"simulated": 0, "why": "search_command_exit_1"},
        {"simulated": 0, "why": "search_command_exit_1"},
    )
    expect(
        "old_version_dialog_not_a_runtime_branch",
        {"runtime_version_probe": RUNTIME_VERSION_PROBE, "contract": VERSION_CONTRACT},
        {"runtime_version_probe": 0, "contract": "2.1.332"},
    )

    print(f"executed={len(EXECUTED)} network={NETWORK}")
    if EXECUTED or NETWORK:
        FAILS.append("fixture executed a command or opened a network call")
    if FAILS:
        print(f"result=fail count={len(FAILS)}")
        for item in FAILS:
            print(item)
        sys.exit(1)
    print("result=pass")


if __name__ == "__main__":
    main()
