#!/usr/bin/env python3
"""按 2026-10-31 读到的 Claude 帮助中心，给任务特征一个路由。

这是本地判决，不是 Claude 的路由器。不登录，不读密钥，不访问网络。
页上没有写成数字的项（空闲几分钟、token 数小时内过期）这里不补。

规则对应的四页写在 README.md。
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED = [
    "plan",
    "unified_on",
    "chat_on",
    "cloud_code_exec_on",
    "compliance",
    "needs_code",
    "needs_files",
    "needs_network",
    "needs_local_folder",
    "needs_local_mcp",
    "needs_computer_use",
    "desktop_online",
    "remote_control",
    "started_from",
    "egress",
    "local_mcp_mdm_off",
]

PLANS = {"pro", "max", "ultra", "team", "enterprise"}
EGRESS = {None, "off", "package_managers", "custom", "all"}
COMPLIANCE = {None, "zdr", "hipaa", "cmek"}
STARTED = {"web", "desktop", "mobile", "scheduled"}
BOOLS = [
    "unified_on",
    "chat_on",
    "cloud_code_exec_on",
    "needs_code",
    "needs_files",
    "needs_network",
    "needs_local_folder",
    "needs_local_mcp",
    "needs_computer_use",
    "desktop_online",
    "remote_control",
    "local_mcp_mdm_off",
]
ROUTES = {
    "stay_chat",
    "escalate_cloud",
    "need_local_link",
    "keep_split",
    "blocked_capability",
    "blocked_desktop",
    "blocked_remote",
    "blocked_local_mcp",
    "computer_use_unlisted",
}


def result(route: str, why: str, notes: list[str] | None = None) -> dict:
    if route not in ROUTES:
        raise ValueError(route)
    return {"route": route, "why": why, "notes": sorted(notes or [])}


def decide(task: dict) -> dict:
    """给定任务特征和开关，返回留在 chat、升格云，或需要本机链接。"""
    unknown = set(task) - set(REQUIRED)
    missing = [key for key in REQUIRED if key not in task]
    if missing or unknown:
        raise ValueError(f"字段不对 missing={missing} unknown={sorted(unknown)}")
    for key in BOOLS:
        if not isinstance(task[key], bool):
            raise ValueError(f"{key} 必须是布尔")
    if task["plan"] not in PLANS:
        raise ValueError(f"未知计划 {task['plan']}")
    if task["egress"] not in EGRESS:
        raise ValueError(f"未知出站 {task['egress']}")
    if task["compliance"] not in COMPLIANCE:
        raise ValueError(f"未知合规标记 {task['compliance']}")
    if task["started_from"] not in STARTED:
        raise ValueError(f"未知入口 {task['started_from']}")
    if task["plan"] != "enterprise" and task["compliance"] is not None:
        raise ValueError("ZDR、HIPAA、CMEK 只在 Enterprise 管理文里写到")

    plan = task["plan"]
    if plan == "enterprise" and task["compliance"] in {"zdr", "hipaa", "cmek"}:
        return result(
            "keep_split",
            "ZDR、HIPAA-ready 或 CMEK 的组织现在打不开 Chat and Cowork unified。",
        )

    if plan == "enterprise" and (
        not task["chat_on"] or not task["cloud_code_exec_on"]
    ):
        return result(
            "blocked_capability",
            "统一体验要求 Chat 和 Cloud code execution and file creation 都开着。缺一项就不会打开。11 月 16 日之后，也要等两项都开。",
        )

    if plan == "enterprise" and not task["unified_on"]:
        return result(
            "keep_split",
            "现有 Enterprise 组织里这项默认关。关着时，chat 和 Cowork 仍是分开的选项。",
        )

    if plan == "team" and not task["unified_on"]:
        return result(
            "keep_split",
            "Team 上统一体验是 beta，要打开 Chat and Cowork unified 才有。",
        )

    if plan in {"pro", "max", "ultra"} and not task["unified_on"]:
        return result(
            "keep_split",
            "Pro、Max、Ultra 分批放开。输入框还显示 Chat 和 Cowork 时，这个账号还没有统一界面。",
        )

    if task["needs_computer_use"] and plan not in {"pro", "max", "ultra"}:
        return result(
            "computer_use_unlisted",
            "用户文只把 computer use 写成 Pro、Max、Ultra 上的 beta。Enterprise 和 Team 这页没有写。",
        )

    wants_local = (
        task["needs_local_folder"]
        or task["needs_local_mcp"]
        or task["needs_computer_use"]
    )
    if wants_local:
        mcp_only = (
            task["needs_local_mcp"]
            and task["local_mcp_mdm_off"]
            and not task["needs_local_folder"]
            and not task["needs_computer_use"]
        )
        if mcp_only:
            return result(
                "blocked_local_mcp",
                "isLocalDevMcpEnabled 为 false 时，云会话经桌面只剩受文件夹限制的文件工具。这条任务只要本地 MCP。",
            )
        if not task["desktop_online"]:
            return result(
                "blocked_desktop",
                "碰本机文件或应用要 Claude Desktop 开着。桌面离线时，云会话到不了这台设备。",
            )
        remote_entry = task["started_from"] in {"web", "mobile", "scheduled"}
        if remote_entry and not task["remote_control"]:
            return result(
                "blocked_remote",
                "Remote control 关掉时，web、手机和定时任务用不了成员链接的电脑。",
            )
        notes = ["local_mcp_not_in_cloud_vm"] if task["needs_local_mcp"] else []
        if task["needs_local_mcp"]:
            why = "本地 MCP 进程不在云会话里跑。要桌面链接着，云会话才碰得到这台设备。"
        elif task["needs_computer_use"]:
            why = "用户文把 computer use 写成 Pro、Max、Ultra 的 beta，要在成员的电脑上操作，桌面得开着。"
        else:
            why = "本机文件夹经 Claude Desktop。云会话只碰到成员连接过的文件夹。"
        return result("need_local_link", why, notes)

    if task["needs_code"] or task["needs_files"]:
        notes = []
        if task["needs_network"] and task["egress"] == "off":
            notes.append("egress_off")
            why = "要跑代码或处理文件时，同一段对话进隔离云会话。出站是关的，备注 egress_off。"
        else:
            why = "要跑代码或处理文件时，同一段对话进隔离云会话。"
        return result("escalate_cloud", why, notes)

    return result(
        "stay_chat",
        "不跑代码、不处理文件，就留在 chat。简单问题仍是快速回答。",
    )


def load_cases() -> list[dict]:
    raw = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
    base = raw["base"]
    cases = []
    seen: set[str] = set()
    for item in raw["cases"]:
        if item["id"] in seen:
            raise ValueError(f"重复 id {item['id']}")
        seen.add(item["id"])
        task = copy.deepcopy(base)
        task.update(item.get("patch", {}))
        cases.append({"id": item["id"], "task": task, "expect": item["expect"]})
    return cases


def show_notes(notes: list[str]) -> str:
    return ",".join(notes) if notes else "-"


def check_max_matches_pro() -> None:
    """Max 和 Pro 在架构文、用户文里同一档。样例没有单列 Max，这里对一次。"""
    common = {
        "unified_on": True,
        "chat_on": True,
        "cloud_code_exec_on": True,
        "compliance": None,
        "needs_code": False,
        "needs_files": True,
        "needs_network": False,
        "needs_local_folder": False,
        "needs_local_mcp": False,
        "needs_computer_use": False,
        "desktop_online": True,
        "remote_control": True,
        "started_from": "web",
        "egress": None,
        "local_mcp_mdm_off": False,
    }
    pro = decide({**common, "plan": "pro"})
    max_plan = decide({**common, "plan": "max"})
    if pro["route"] != "escalate_cloud" or pro["route"] != max_plan["route"]:
        raise SystemExit("max 与 pro 的升格判决不一致")
    if pro["notes"] != max_plan["notes"]:
        raise SystemExit("max 与 pro 的备注不一致")


def main() -> int:
    check_max_matches_pro()
    try:
        decide({"plan": "free"})
    except ValueError:
        pass
    else:
        raise SystemExit("未知计划应当拒绝")

    failed = 0
    cases = load_cases()
    for case in cases:
        got = decide(case["task"])
        expect = case["expect"]
        route_ok = got["route"] == expect["route"]
        notes_ok = got["notes"] == expect["notes"]
        mark = "ok" if route_ok and notes_ok else "FAIL"
        if mark == "FAIL":
            failed += 1
        print(
            f"{mark}\t{case['id']}\t{got['route']}\t{show_notes(got['notes'])}\t{got['why']}"
        )
        if not route_ok or not notes_ok:
            print(
                f"  expect route={expect['route']} notes={show_notes(expect['notes'])}"
            )
    print(f"cases={len(cases)} failed={failed}")
    if failed:
        print("result=fail")
        return 1
    print("result=pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
