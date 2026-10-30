#!/usr/bin/env python3
"""订单查询 + 物流：有损交接，和折进同一上下文之后的差别。

这是脚本，不是模型。它不调用官方 single-agent-loop-kit，也不需要密钥。
四条路径共用同一份夹具：

- handoff-drop：订单专员的摘要丢掉运单号，物流专员按自己的提示拒绝。
- handoff-stop：摘要里有运单号，编排器拿到摘要就停，不再调物流。
- same-context：原始 JSON 留在同一个上下文，脚本接着调 track_shipment。
- early-answer：已经折进主循环，却只凭订单状态作答。

评分只看回复里有没有夹具中的预计送达日。缺运单号时工具必须拒绝，这是单测，不经过「模型」。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ORDER_ID = "QS-2048"
ETA = "2026-11-02"


def load_json(name: str) -> dict:
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


ORDERS = load_json("orders.json")
SHIPMENTS = load_json("shipments.json")


def lookup_order(order_id: str) -> dict:
    row = ORDERS.get(order_id)
    if row is None:
        return {"ok": False, "message": f"没有订单 {order_id}。"}
    return {"ok": True, **row}


def track_shipment(tracking_id: str | None) -> dict:
    """硬限制在工具里。提示词里那句「没有运单号就别查」从这里执行。"""
    if not tracking_id or not str(tracking_id).startswith("TRK-"):
        return {
            "ok": False,
            "message": "没有运单号。先 lookup_order，把 tracking_id 原样传进来。",
        }
    row = SHIPMENTS.get(tracking_id)
    if row is None:
        return {"ok": False, "message": f"运单 {tracking_id} 不存在。"}
    return {"ok": True, **row}


def orders_summary(order: dict, *, keep_tracking: bool) -> str:
    """订单专员被要求只说商品和状态，摘要可以丢掉运单号。"""
    base = f"订单 {order['order_id']}，{order['item']}，状态已发货。"
    if keep_tracking:
        return base + f"运单 {order['tracking_id']}。"
    return base


def shipping_from_brief(brief: str) -> tuple[str, bool]:
    """物流专员只读摘要。摘要里没有 TRK- 开头的运单号，就拒绝。"""
    token = next((part for part in brief.split() if part.startswith("TRK-")), None)
    if token is None:
        return "摘要里没有运单号，还不能查。", False
    shipment = track_shipment(token.rstrip("。"))
    if not shipment.get("ok"):
        return shipment["message"], False
    return (
        f"承运商 {shipment['carrier']}，状态 {shipment['state']}，"
        f"预计 {shipment['eta']}，{shipment['last_event']}。"
    ), True


def grade(text: str) -> str:
    return "pass" if ETA in text else "fail"


def window_chars(parts: list[str]) -> int:
    return sum(len(part) for part in parts)


def run_cases() -> list[dict]:
    order = lookup_order(ORDER_ID)
    assert order["ok"]

    dropped = orders_summary(order, keep_tracking=False)
    ship_text, ship_called = shipping_from_brief(dropped)
    handoff_drop_final = dropped + ship_text

    kept = orders_summary(order, keep_tracking=True)
    handoff_stop_final = kept + "需要的话我再让物流查预计到达。"

    shipment = track_shipment(order["tracking_id"])
    same_final = (
        f"订单 {order['order_id']} 已发货。承运商 {shipment['carrier']}，"
        f"预计送达 {shipment['eta']}，{shipment['last_event']}。"
    )

    early_final = (
        f"订单 {order['order_id']} 已发货，运单 {order['tracking_id']}。"
        "订单上没有送达日。"
    )

    refusal = track_shipment(None)

    return [
        {
            "name": "handoff-drop",
            "windows": 3,
            "tools": ["lookup_order", "shipping_refused"],
            "crossed": dropped,
            "final": handoff_drop_final,
            "grade": grade(handoff_drop_final),
            "chars": window_chars([json.dumps(order, ensure_ascii=False), dropped, ship_text]),
            "shipping_called": ship_called,
        },
        {
            "name": "handoff-stop",
            "windows": 2,
            "tools": ["lookup_order"],
            "crossed": kept,
            "final": handoff_stop_final,
            "grade": grade(handoff_stop_final),
            "chars": window_chars([json.dumps(order, ensure_ascii=False), kept]),
            "shipping_called": False,
        },
        {
            "name": "same-context",
            "windows": 1,
            "tools": ["lookup_order", "track_shipment"],
            "crossed": json.dumps({"order": order, "shipment": shipment}, ensure_ascii=False),
            "final": same_final,
            "grade": grade(same_final),
            "chars": window_chars(
                [json.dumps(order, ensure_ascii=False), json.dumps(shipment, ensure_ascii=False)]
            ),
            "shipping_called": True,
        },
        {
            "name": "early-answer",
            "windows": 1,
            "tools": ["lookup_order"],
            "crossed": json.dumps(order, ensure_ascii=False),
            "final": early_final,
            "grade": grade(early_final),
            "chars": window_chars([json.dumps(order, ensure_ascii=False)]),
            "shipping_called": False,
        },
        {
            "name": "tool-refusal",
            "windows": 0,
            "tools": ["track_shipment"],
            "crossed": "",
            "final": refusal["message"],
            "grade": "pass" if refusal["ok"] is False and ETA not in refusal["message"] else "fail",
            "chars": len(refusal["message"]),
            "shipping_called": False,
        },
    ]


def check_fold_map() -> list[str]:
    mapped = json.loads((ROOT / "fold_map.json").read_text(encoding="utf-8"))
    by_file: dict[str, list[str]] = {}
    for row in mapped:
        by_file.setdefault(row["file"], []).append(row["line"])
    problems: list[str] = []
    for rel, lines in by_file.items():
        text = (ROOT / rel).read_text(encoding="utf-8")
        actual = [line for line in text.splitlines() if line.strip()]
        if actual != lines:
            problems.append(f"{rel} 和 fold_map.json 不一致")
    skill = (ROOT / "skills" / "order-tracking" / "SKILL.md").read_text(encoding="utf-8")
    if "tracking_id" not in skill or "track_shipment" not in skill:
        problems.append("技能正文没有写明先取 tracking_id 再调 track_shipment")
    if "俏皮" in skill or "一步一步" in skill:
        problems.append("技能正文留下了人设或旧模型喊话")
    return problems


def main() -> int:
    lines: list[str] = []
    order = lookup_order(ORDER_ID)
    shipment = track_shipment(order["tracking_id"])
    lines.append("== fixture ==")
    lines.append(
        f"order={order['order_id']} status={order['status']} tracking_id={order['tracking_id']}"
    )
    lines.append(
        f"shipment eta={shipment['eta']} carrier={shipment['carrier']} state={shipment['state']}"
    )

    expected = {
        "handoff-drop": "fail",
        "handoff-stop": "fail",
        "same-context": "pass",
        "early-answer": "fail",
        "tool-refusal": "pass",
    }
    cases = run_cases()
    mismatches: list[str] = []
    for case in cases:
        lines.append(f"== {case['name']} ==")
        lines.append(
            f"windows={case['windows']} tools={','.join(case['tools'])} "
            f"shipping_called={str(case['shipping_called']).lower()} chars={case['chars']}"
        )
        if case["crossed"]:
            lines.append(f"crossed={case['crossed']}")
        lines.append(f"final={case['final']}")
        lines.append(f"grade={case['grade']}")
        if case["grade"] != expected[case["name"]]:
            mismatches.append(case["name"])

    lines.append("== prompt-sort ==")
    mapped = json.loads((ROOT / "fold_map.json").read_text(encoding="utf-8"))
    for row in mapped:
        lines.append(f"{row['bucket']}\t{row['file']}\t{row['line']}")
    problems = check_fold_map()
    lines.append(f"prompt_lines={len(mapped)} unmapped_or_drift={len(problems)}")
    for problem in problems:
        lines.append(f"problem={problem}")

    text = "\n".join(lines)
    print(text)
    if mismatches or problems:
        print("result=fail", file=sys.stderr)
        return 1
    print("result=pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
