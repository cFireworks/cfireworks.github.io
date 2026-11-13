#!/usr/bin/env python3
"""伪控制环：InstructionsLoaded 只观察，拦不住加载，也改不了正文。

不调用 API，不读密钥，不访问网络，不启动 Claude Code。
假一次会话开头的急加载（load_reason=session_start），
一次嵌套 CLAUDE.md（nested_traversal），
一次带 paths 的条件规则（path_glob_match），
一次 CLAUDE.md import AGENTS.md（include），
一次压缩之后的指令重载（compact），
一次 CLAUDE.md 指向 AGENTS.md 的 symlink（按普通 CLAUDE.md 急加载），
一次经 Project instructions 设置直接读取的 AGENTS.md（事件不开火）。

处理器是 il_exit2、il_block_decision、il_additional_context、il_discarded、
il_audit_log、il_with_if、il_env_write、sessionstart_compact_stdout、none。
一次只挂一只。这不是 settings 里的 hook。

sessionstart_compact_stdout 把指南里那段 echo 记进模型上下文，
是对 Automate actions with hooks 里 Re-inject context after compaction 的模拟。
不是 Claude Code。压缩之后 InstructionsLoaded 的 compact 和 SessionStart 的 compact
谁先跑，两页没有写。夹具不排先后。
"""

from __future__ import annotations

from dataclasses import dataclass

HANDLERS = frozenset(
    {
        "none",
        "il_exit2",
        "il_block_decision",
        "il_additional_context",
        "il_discarded",
        "il_audit_log",
        "il_with_if",
        "il_env_write",
        "sessionstart_compact_stdout",
    }
)
IL_HANDLERS = frozenset(
    {
        "il_exit2",
        "il_block_decision",
        "il_additional_context",
        "il_discarded",
        "il_audit_log",
        "il_with_if",
        "il_env_write",
    }
)
LOAD_REASONS = frozenset(
    {
        "session_start",
        "nested_traversal",
        "path_glob_match",
        "include",
        "compact",
    }
)
# 指南原文。夹具不改字。
GUIDE_STDOUT = (
    "Reminder: use Bun, not npm. Run bun test before committing. "
    "Current sprint: auth refactor."
)
# 夹具自己的句子。页上没有把 additionalContext 写在这只事件上。
EXTRA = "敏感目录的规则不要进上下文"
STDOUT_LINE = "提醒：嵌套规则已加载"
BLOCK_REASON = "敏感仓库的嵌套 CLAUDE.md 不许进上下文"
# hooks 页例子。根上的 CLAUDE.md，memory_type 为 Project。
ROOT_CLAUDE = "/Users/my-project/CLAUDE.md"
# 下面这些路径是夹具自己的。hooks 页的例子 JSON 没有给。
NESTED_CLAUDE = "/Users/my-project/pkg/CLAUDE.md"
NESTED_TRIGGER = "/Users/my-project/pkg/main.py"
# globs 的字符串照记忆页 paths 的例子。hooks 页只说它来自 paths: frontmatter。
RULE_FILE = "/Users/my-project/.claude/rules/api.md"
RULE_TRIGGER = "/Users/my-project/src/api/handler.ts"
RULE_GLOBS = "src/api/**/*.ts"
AGENTS = "/Users/my-project/AGENTS.md"


@dataclass(frozen=True)
class Load:
    kind: str
    fires: bool
    load_reason: str
    file_path: str
    memory_type: str
    globs: str
    trigger_file_path: str
    parent_file_path: str


# memory_type 除了根上那条照着例子写 Project，其余行夹具也填 Project。
# 页上没有把嵌套文件、规则、AGENTS.md 逐条映射到四个取值。
EAGER = Load(
    kind="eager",
    fires=True,
    load_reason="session_start",
    file_path=ROOT_CLAUDE,
    memory_type="Project",
    globs="",
    trigger_file_path="",
    parent_file_path="",
)
NESTED = Load(
    kind="nested",
    fires=True,
    load_reason="nested_traversal",
    file_path=NESTED_CLAUDE,
    memory_type="Project",
    globs="",
    trigger_file_path=NESTED_TRIGGER,
    parent_file_path="",
)
PATH_RULE = Load(
    kind="path_rule",
    fires=True,
    load_reason="path_glob_match",
    file_path=RULE_FILE,
    memory_type="Project",
    globs=RULE_GLOBS,
    trigger_file_path=RULE_TRIGGER,
    parent_file_path="",
)
INCLUDE = Load(
    kind="include",
    fires=True,
    load_reason="include",
    file_path=AGENTS,
    memory_type="Project",
    globs="",
    trigger_file_path="",
    parent_file_path=ROOT_CLAUDE,
)
COMPACT = Load(
    kind="compact",
    fires=True,
    load_reason="compact",
    file_path=ROOT_CLAUDE,
    memory_type="Project",
    globs="",
    trigger_file_path="",
    parent_file_path="",
)
# symlink 按普通 CLAUDE.md 急加载。不解析链接目标。file_path 用链接这一侧。
# 目标路径会不会出现在 file_path 里，专项没有写。
SYMLINK = Load(
    kind="symlink",
    fires=True,
    load_reason="session_start",
    file_path=ROOT_CLAUDE,
    memory_type="Project",
    globs="",
    trigger_file_path="",
    parent_file_path="",
)
# 设置直接读取。事件不开火。正文仍在上下文里。没有 load_reason。
AGENTS_DIRECT = Load(
    kind="agents_direct",
    fires=False,
    load_reason="",
    file_path=AGENTS,
    memory_type="Project",
    globs="",
    trigger_file_path="",
    parent_file_path="",
)


def matcher_hits(matcher: str, value: str) -> bool:
    """空 matcher 对上每一次。非空只按 `|` 切开，整段相等。

    参考页写多数事件也接受逗号。夹具不模拟逗号，也不模拟正则。
    """
    if matcher == "":
        return True
    parts = [part.strip() for part in matcher.split("|")]
    return value in parts


def matcher_label(matcher: str, used: bool) -> str:
    if not used:
        return "na"
    if matcher == "":
        return "empty"
    return matcher


def load_blocked(code: int, payload: dict | None) -> bool:
    """exit 2 被忽略。没有 decision control。

    顶层 decision、continue、systemMessage 都读过，不拿来当闸。
    """
    if code == 2:
        return False
    if isinstance(payload, dict):
        if payload.get("decision") == "block":
            return False
        if payload.get("continue") is False:
            return False
        if payload.get("systemMessage"):
            return False
    return False


def il_model_context(payload: dict | None, stdout: str) -> str:
    """JSON 字段进不了模型。纯文本 stdout 也不进。

    投放点列表和 Exit code 0 的例外名单都没有 InstructionsLoaded。
    """
    del payload, stdout
    return ""


def audit_line(load: Load) -> str:
    """只记页上有的字段。空的附加字段不写。"""
    parts = [load.load_reason, load.file_path, f"memory_type={load.memory_type}"]
    if load.globs:
        parts.append(f"globs={load.globs}")
    if load.trigger_file_path:
        parts.append(f"trigger={load.trigger_file_path}")
    if load.parent_file_path:
        parts.append(f"parent={load.parent_file_path}")
    return " ".join(parts)


def il_output(handler: str) -> tuple[int, dict | None, str]:
    """返回退出码、JSON、纯文本通道。il_with_if 若真跑起来会 exit 2。"""
    if handler in ("il_exit2", "il_with_if"):
        return 2, None, ""
    if handler == "il_block_decision":
        return 0, {
            "decision": "block",
            "reason": BLOCK_REASON,
            "systemMessage": "拦住了",
            "continue": False,
        }, ""
    if handler == "il_additional_context":
        return 0, {
            "systemMessage": "不要加载",
            "continue": False,
            "hookSpecificOutput": {
                "hookEventName": "InstructionsLoaded",
                "additionalContext": EXTRA,
            },
        }, STDOUT_LINE
    if handler == "il_discarded":
        return 0, {
            "continue": False,
            "systemMessage": "这句不会成为闸",
        }, ""
    if handler in ("il_audit_log", "il_env_write"):
        return 0, None, ""
    raise SystemExit(f"not an InstructionsLoaded handler {handler}")


@dataclass(frozen=True)
class Record:
    name: str
    kind: str
    handler: str
    matcher: str
    if_set: int
    load_reason: str
    il_fired: int
    loaded: int
    audit_logged: int
    audit_line: str
    model_has_il_context: int
    model_context: str
    sessionstart_fired: int
    model_has_sessionstart_stdout: int
    env_persisted: int

    def line(self) -> str:
        return " ".join(
            [
                f"case={self.name}",
                f"kind={self.kind}",
                f"handler={self.handler}",
                f"matcher={self.matcher}",
                f"if_set={self.if_set}",
                f"load_reason={self.load_reason}",
                f"il_fired={self.il_fired}",
                f"loaded={self.loaded}",
                f"audit_logged={self.audit_logged}",
                f"model_has_il_context={self.model_has_il_context}",
                f"sessionstart_fired={self.sessionstart_fired}",
                f"model_has_sessionstart_stdout={self.model_has_sessionstart_stdout}",
                f"env_persisted={self.env_persisted}",
            ]
        )


def settle(
    name: str,
    load: Load,
    handler: str,
    matcher: str = "",
    if_set: bool = False,
) -> Record:
    """一只处理器挂在这一次加载上。没跑起来的钩，不改 loaded。"""
    if handler not in HANDLERS:
        raise SystemExit(f"unknown handler {handler}")
    if load.kind not in {
        "eager",
        "nested",
        "path_rule",
        "include",
        "compact",
        "symlink",
        "agents_direct",
    }:
        raise SystemExit(f"unknown kind {load.kind}")
    if load.fires and load.load_reason not in LOAD_REASONS:
        raise SystemExit(f"unknown load_reason {load.load_reason}")
    if load.globs and load.load_reason != "path_glob_match":
        raise SystemExit("globs set outside path_glob_match")
    if load.load_reason == "path_glob_match" and not load.globs:
        raise SystemExit("path_glob_match missing globs")
    if load.trigger_file_path and load.load_reason not in {
        "nested_traversal",
        "path_glob_match",
    }:
        raise SystemExit("trigger_file_path set outside a lazy load")
    if load.parent_file_path and load.load_reason != "include":
        raise SystemExit("parent_file_path set outside include")
    if load.load_reason == "include" and not load.parent_file_path:
        raise SystemExit("include missing parent_file_path")

    flag = 1 if if_set else 0
    reason = load.load_reason if load.fires else "na"
    # 指令文件进了上下文。这只事件拦不住这件事。直接读取的 AGENTS.md 也在上下文里。
    loaded = 1

    if handler == "none":
        return Record(
            name=name,
            kind=load.kind,
            handler=handler,
            matcher="na",
            if_set=flag,
            load_reason=reason,
            il_fired=0,
            loaded=loaded,
            audit_logged=0,
            audit_line="",
            model_has_il_context=0,
            model_context="",
            sessionstart_fired=0,
            model_has_sessionstart_stdout=0,
            env_persisted=0,
        )

    if handler == "sessionstart_compact_stdout":
        # matcher 对的是 SessionStart 的 source，不是 load_reason。
        # 只有压缩之后 source 才是 compact。嵌套懒加载不会再开一次 SessionStart。
        source = "compact" if load.kind == "compact" else ""
        fired = source != "" and matcher_hits(matcher, source)
        text = GUIDE_STDOUT if fired else ""
        return Record(
            name=name,
            kind=load.kind,
            handler=handler,
            matcher=matcher_label(matcher, True),
            if_set=flag,
            load_reason=reason,
            il_fired=0,
            loaded=loaded,
            audit_logged=0,
            audit_line="",
            model_has_il_context=0,
            model_context=text,
            sessionstart_fired=1 if fired else 0,
            model_has_sessionstart_stdout=1 if text else 0,
            env_persisted=0,
        )

    if handler not in IL_HANDLERS:
        raise SystemExit(f"unhandled combination {load.kind} {handler}")

    # 事件不开火，或者 if 写在非工具事件上，或者 matcher 没对上：钩不跑。
    # 文件照样在上下文里。
    runs = (
        load.fires
        and not if_set
        and matcher_hits(matcher, load.load_reason)
    )
    label = matcher_label(matcher, True)
    if not runs:
        return Record(
            name=name,
            kind=load.kind,
            handler=handler,
            matcher=label,
            if_set=flag,
            load_reason=reason,
            il_fired=0,
            loaded=loaded,
            audit_logged=0,
            audit_line="",
            model_has_il_context=0,
            model_context="",
            sessionstart_fired=0,
            model_has_sessionstart_stdout=0,
            env_persisted=0,
        )

    code, payload, stdout = il_output(handler)
    if load_blocked(code, payload):
        raise SystemExit("InstructionsLoaded was treated as a gate")
    context = il_model_context(payload, stdout)
    logged = handler == "il_audit_log"
    return Record(
        name=name,
        kind=load.kind,
        handler=handler,
        matcher=label,
        if_set=flag,
        load_reason=reason,
        il_fired=1,
        loaded=loaded,
        audit_logged=1 if logged else 0,
        audit_line=audit_line(load) if logged else "",
        model_has_il_context=1 if context else 0,
        model_context=context,
        sessionstart_fired=0,
        model_has_sessionstart_stdout=0,
        # 这只事件没有 CLAUDE_ENV_FILE。想写也没有那个变量。
        env_persisted=0,
    )


def printed_records() -> list[Record]:
    rows = [
        settle("eager_il_exit2", EAGER, "il_exit2", matcher="session_start"),
        settle("eager_il_block_decision", EAGER, "il_block_decision", matcher=""),
        settle("eager_il_additional_context", EAGER, "il_additional_context", matcher=""),
        settle("eager_il_discarded", EAGER, "il_discarded", matcher="session_start"),
        settle("eager_il_with_if", EAGER, "il_with_if", matcher="session_start", if_set=True),
        settle("eager_il_env_write", EAGER, "il_env_write", matcher="session_start"),
        settle("eager_none", EAGER, "none"),
        settle("eager_matcher_startup", EAGER, "il_exit2", matcher="startup"),
        settle("nested_il_exit2", NESTED, "il_exit2", matcher="nested_traversal"),
        settle("nested_il_audit_log", NESTED, "il_audit_log", matcher=""),
        settle(
            "nested_matcher_session_start",
            NESTED,
            "il_exit2",
            matcher="session_start",
        ),
        settle("path_il_block_decision", PATH_RULE, "il_block_decision", matcher=""),
        settle("path_il_audit_log", PATH_RULE, "il_audit_log", matcher="path_glob_match"),
        settle("compact_il_exit2", COMPACT, "il_exit2", matcher="compact"),
        settle("compact_il_audit_log", COMPACT, "il_audit_log", matcher="compact"),
        settle(
            "compact_il_additional_context",
            COMPACT,
            "il_additional_context",
            matcher="compact",
        ),
        settle(
            "compact_sessionstart_compact_stdout",
            COMPACT,
            "sessionstart_compact_stdout",
            matcher="compact",
        ),
        settle(
            "nested_sessionstart_compact_stdout",
            NESTED,
            "sessionstart_compact_stdout",
            matcher="compact",
        ),
        settle("agents_direct_il_exit2", AGENTS_DIRECT, "il_exit2", matcher=""),
        settle("agents_direct_il_audit_log", AGENTS_DIRECT, "il_audit_log", matcher=""),
        settle("include_il_exit2", INCLUDE, "il_exit2", matcher="include"),
        settle("include_il_audit_log", INCLUDE, "il_audit_log", matcher=""),
        settle("symlink_il_exit2", SYMLINK, "il_exit2", matcher="session_start"),
    ]
    return rows


def expect(record: Record, **kwargs: object) -> None:
    for key, value in kwargs.items():
        got = getattr(record, key)
        if got != value:
            raise SystemExit(f"{record.name} {key}: got {got!r} want {value!r}")


def check(records: dict[str, Record]) -> None:
    expect(
        records["eager_il_exit2"],
        kind="eager",
        handler="il_exit2",
        matcher="session_start",
        if_set=0,
        load_reason="session_start",
        il_fired=1,
        loaded=1,
        audit_logged=0,
        model_has_il_context=0,
        model_context="",
        sessionstart_fired=0,
        model_has_sessionstart_stdout=0,
        env_persisted=0,
    )
    expect(
        records["eager_il_block_decision"],
        handler="il_block_decision",
        matcher="empty",
        il_fired=1,
        loaded=1,
        model_has_il_context=0,
        model_context="",
        env_persisted=0,
    )
    expect(
        records["eager_il_additional_context"],
        handler="il_additional_context",
        matcher="empty",
        il_fired=1,
        loaded=1,
        model_has_il_context=0,
        model_context="",
        model_has_sessionstart_stdout=0,
    )
    if EXTRA in records["eager_il_additional_context"].model_context:
        raise SystemExit("additionalContext entered model context")
    if STDOUT_LINE in records["eager_il_additional_context"].model_context:
        raise SystemExit("InstructionsLoaded stdout entered model context")
    expect(
        records["eager_il_discarded"],
        handler="il_discarded",
        il_fired=1,
        loaded=1,
        model_has_il_context=0,
        model_context="",
    )
    expect(
        records["eager_il_with_if"],
        handler="il_with_if",
        matcher="session_start",
        if_set=1,
        il_fired=0,
        loaded=1,
        audit_logged=0,
        model_context="",
    )
    expect(
        records["eager_il_env_write"],
        handler="il_env_write",
        il_fired=1,
        loaded=1,
        env_persisted=0,
    )
    expect(
        records["eager_none"],
        handler="none",
        matcher="na",
        il_fired=0,
        loaded=1,
        audit_logged=0,
        model_has_il_context=0,
        env_persisted=0,
    )
    expect(
        records["eager_matcher_startup"],
        handler="il_exit2",
        matcher="startup",
        load_reason="session_start",
        il_fired=0,
        loaded=1,
    )
    expect(
        records["nested_il_exit2"],
        kind="nested",
        load_reason="nested_traversal",
        il_fired=1,
        loaded=1,
        model_has_il_context=0,
    )
    nested_audit = records["nested_il_audit_log"]
    expect(
        nested_audit,
        handler="il_audit_log",
        matcher="empty",
        load_reason="nested_traversal",
        il_fired=1,
        loaded=1,
        audit_logged=1,
        model_has_il_context=0,
    )
    if "nested_traversal" not in nested_audit.audit_line:
        raise SystemExit("audit missed nested_traversal")
    if NESTED_TRIGGER not in nested_audit.audit_line:
        raise SystemExit("audit missed trigger_file_path")
    if "globs=" in nested_audit.audit_line or "parent=" in nested_audit.audit_line:
        raise SystemExit("nested audit grew fields the section does not assign here")
    expect(
        records["nested_matcher_session_start"],
        matcher="session_start",
        load_reason="nested_traversal",
        il_fired=0,
        loaded=1,
        audit_logged=0,
    )
    expect(
        records["path_il_block_decision"],
        kind="path_rule",
        load_reason="path_glob_match",
        il_fired=1,
        loaded=1,
        model_has_il_context=0,
        audit_logged=0,
    )
    path_audit = records["path_il_audit_log"]
    expect(
        path_audit,
        load_reason="path_glob_match",
        il_fired=1,
        loaded=1,
        audit_logged=1,
    )
    if f"globs={RULE_GLOBS}" not in path_audit.audit_line:
        raise SystemExit("audit missed globs")
    if RULE_TRIGGER not in path_audit.audit_line:
        raise SystemExit("audit missed the path-rule trigger")
    compact_audit = records["compact_il_audit_log"]
    expect(
        compact_audit,
        kind="compact",
        load_reason="compact",
        matcher="compact",
        il_fired=1,
        loaded=1,
        audit_logged=1,
        model_has_il_context=0,
        model_has_sessionstart_stdout=0,
    )
    if not compact_audit.audit_line.startswith("compact "):
        raise SystemExit("compact audit line drifted")
    if "globs=" in compact_audit.audit_line or "trigger=" in compact_audit.audit_line:
        raise SystemExit("compact audit grew lazy-only fields")
    expect(
        records["compact_il_exit2"],
        load_reason="compact",
        il_fired=1,
        loaded=1,
        model_has_sessionstart_stdout=0,
        model_context="",
    )
    expect(
        records["compact_il_additional_context"],
        load_reason="compact",
        il_fired=1,
        loaded=1,
        model_has_il_context=0,
        model_context="",
        model_has_sessionstart_stdout=0,
    )
    injected = records["compact_sessionstart_compact_stdout"]
    expect(
        injected,
        handler="sessionstart_compact_stdout",
        matcher="compact",
        load_reason="compact",
        il_fired=0,
        loaded=1,
        audit_logged=0,
        model_has_il_context=0,
        sessionstart_fired=1,
        model_has_sessionstart_stdout=1,
        model_context=GUIDE_STDOUT,
        env_persisted=0,
    )
    expect(
        records["nested_sessionstart_compact_stdout"],
        kind="nested",
        load_reason="nested_traversal",
        sessionstart_fired=0,
        model_has_sessionstart_stdout=0,
        model_context="",
        loaded=1,
        il_fired=0,
    )
    expect(
        records["agents_direct_il_exit2"],
        kind="agents_direct",
        load_reason="na",
        il_fired=0,
        loaded=1,
        audit_logged=0,
        model_context="",
    )
    expect(
        records["agents_direct_il_audit_log"],
        handler="il_audit_log",
        load_reason="na",
        il_fired=0,
        loaded=1,
        audit_logged=0,
        audit_line="",
    )
    expect(
        records["include_il_exit2"],
        kind="include",
        load_reason="include",
        il_fired=1,
        loaded=1,
        model_has_il_context=0,
    )
    include_audit = records["include_il_audit_log"]
    expect(
        include_audit,
        load_reason="include",
        il_fired=1,
        loaded=1,
        audit_logged=1,
    )
    if "include " not in include_audit.audit_line or f"parent={ROOT_CLAUDE}" not in include_audit.audit_line:
        raise SystemExit("include audit missed parent_file_path")
    if "globs=" in include_audit.audit_line or "trigger=" in include_audit.audit_line:
        raise SystemExit("include audit grew lazy-only fields")
    expect(
        records["symlink_il_exit2"],
        kind="symlink",
        load_reason="session_start",
        matcher="session_start",
        il_fired=1,
        loaded=1,
        model_context="",
    )

    if any(row.env_persisted != 0 for row in records.values()):
        raise SystemExit("CLAUDE_ENV_FILE was persisted from this event")
    if any(row.loaded != 1 for row in records.values()):
        raise SystemExit("a hook changed whether the file was loaded")
    if any(row.model_has_il_context != 0 for row in records.values()):
        raise SystemExit("InstructionsLoaded delivered model context")

    code, payload, stdout = il_output("il_exit2")
    if code != 2 or payload is not None or stdout:
        raise SystemExit("exit 2 fixture drifted")
    if load_blocked(code, payload):
        raise SystemExit("exit 2 blocked a load")
    blocked_code, blocked_payload, blocked_stdout = il_output("il_block_decision")
    if blocked_code != 0 or blocked_stdout or not isinstance(blocked_payload, dict):
        raise SystemExit("block JSON fixture did not exit 0")
    if blocked_payload.get("decision") != "block" or blocked_payload.get("reason") != BLOCK_REASON:
        raise SystemExit("block JSON fixture lost decision or reason")
    if load_blocked(blocked_code, blocked_payload):
        raise SystemExit("decision block blocked a load")
    if_code, _if_payload, _if_stdout = il_output("il_with_if")
    if if_code != 2:
        raise SystemExit("if fixture would not have exited 2 had it run")
    extra_code, extra_payload, extra_stdout = il_output("il_additional_context")
    if extra_code != 0 or extra_stdout != STDOUT_LINE:
        raise SystemExit("additionalContext fixture drifted")
    nested = extra_payload.get("hookSpecificOutput") if isinstance(extra_payload, dict) else None
    if not isinstance(nested, dict) or nested.get("additionalContext") != EXTRA:
        raise SystemExit("additionalContext fixture lost the nested field")
    if il_model_context(extra_payload, extra_stdout) != "":
        raise SystemExit("model context was built from InstructionsLoaded output")
    discarded_code, discarded_payload, discarded_stdout = il_output("il_discarded")
    if discarded_code != 0 or discarded_stdout:
        raise SystemExit("discarded-field fixture drifted")
    if not isinstance(discarded_payload, dict) or discarded_payload.get("continue") is not False:
        raise SystemExit("discarded-field fixture lost continue")
    if load_blocked(discarded_code, discarded_payload):
        raise SystemExit("continue false blocked a load")

    if matcher_hits("startup", "session_start") or matcher_hits("session_start", "startup"):
        raise SystemExit("startup and session_start were treated as the same string")
    if not matcher_hits("session_start", "session_start"):
        raise SystemExit("session_start matcher missed its own value")
    for reason in LOAD_REASONS:
        if not matcher_hits("", reason):
            raise SystemExit(f"empty matcher missed {reason}")
    if not matcher_hits("path_glob_match|nested_traversal", "nested_traversal"):
        raise SystemExit("pipe matcher drifted")
    if not matcher_hits("path_glob_match|nested_traversal", "path_glob_match"):
        raise SystemExit("pipe matcher missed path_glob_match")
    if matcher_hits("session_start", "nested_traversal"):
        raise SystemExit("session_start matcher caught a lazy load")
    # compact 这个字符串两边都有。字段不是同一个。夹具分开对。
    if COMPACT.load_reason != "compact":
        raise SystemExit("compact load_reason drifted")
    if not matcher_hits("compact", COMPACT.load_reason):
        raise SystemExit("InstructionsLoaded compact matcher missed load_reason")
    startup_on_compact = settle(
        "compact_matcher_startup_probe",
        COMPACT,
        "sessionstart_compact_stdout",
        matcher="startup",
    )
    if startup_on_compact.sessionstart_fired != 0 or startup_on_compact.model_context:
        raise SystemExit("SessionStart startup matcher caught a compact source")
    session_start_on_ss = settle(
        "compact_matcher_session_start_probe",
        COMPACT,
        "sessionstart_compact_stdout",
        matcher="session_start",
    )
    if session_start_on_ss.sessionstart_fired != 0:
        raise SystemExit("SessionStart treated session_start as its compact source")

    if EAGER.file_path != ROOT_CLAUDE or EAGER.memory_type != "Project":
        raise SystemExit("eager fixture drifted from the documented example")
    if EAGER.load_reason != "session_start":
        raise SystemExit("eager load_reason drifted")
    if PATH_RULE.globs != RULE_GLOBS:
        raise SystemExit("globs drifted from the memory-page example")
    if INCLUDE.parent_file_path != ROOT_CLAUDE or INCLUDE.file_path != AGENTS:
        raise SystemExit("include fixture drifted")
    if AGENTS_DIRECT.fires:
        raise SystemExit("direct AGENTS.md fired InstructionsLoaded")
    if not SYMLINK.fires or SYMLINK.load_reason != "session_start":
        raise SystemExit("symlink was not a normal CLAUDE.md load")

    try:
        settle("bad", EAGER, "matcher_opus")
    except SystemExit as exc:
        if "unknown handler" not in str(exc):
            raise
    else:
        raise SystemExit("unknown handler was accepted")


def main() -> None:
    rows = printed_records()
    records = {row.name: row for row in rows}
    if len(records) != len(rows):
        raise SystemExit("duplicate case name")
    check(records)
    for row in rows:
        print(row.line())
    print("result=pass")


if __name__ == "__main__":
    main()
