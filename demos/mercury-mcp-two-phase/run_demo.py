#!/usr/bin/env python3
"""Offline model of a two-phase MCP write contract.

Not the Mercury API. No sockets, no credentials. A chat confirmation
never settles a payment. Only the separate Mercury role can approve
or decline. Note updates apply immediately and do not enter the queue.
"""

from __future__ import annotations

from dataclasses import dataclass, field


CHECKING_START = 1000


@dataclass
class Request:
    id: str
    kind: str
    recipient: str
    amount: int
    status: str
    chat_confirmed: bool = False


@dataclass
class Ledger:
    balance: int = CHECKING_START
    notes: dict[str, str] = field(default_factory=lambda: {"txn_1": ""})
    requests: dict[str, Request] = field(default_factory=dict)
    scopes: set[str] = field(
        default_factory=lambda: {"transactions:request", "transactions:update"}
    )
    # The org policy would let a human send without a second approver.
    # The chat role still cannot settle the request.
    policy_allows_unapproved_send: bool = True
    _n: int = 0

    def request_payment(
        self,
        role: str,
        recipient: str,
        amount: int,
        uncertain_retry: bool = False,
    ) -> str:
        if role != "chat":
            raise SystemExit("FAIL request_payment role")
        if "transactions:request" not in self.scopes:
            return "request_payment ok=false reason=scope_missing"
        if uncertain_retry:
            for rec in self.requests.values():
                if (
                    rec.kind == "payment"
                    and rec.status == "needs_approval"
                    and rec.recipient == recipient
                    and rec.amount == amount
                ):
                    return (
                        f"uncertain_retry id={rec.id} created=false "
                        f"status={rec.status} balance={self.balance}"
                    )
            raise SystemExit("FAIL expected an existing pending request")
        self._n += 1
        rec = Request(
            id=f"pay_{self._n}",
            kind="payment",
            recipient=recipient,
            amount=amount,
            status="needs_approval",
        )
        self.requests[rec.id] = rec
        return (
            f"request_payment id={rec.id} recipient={recipient} amount={amount} "
            f"status={rec.status} balance={self.balance} moved=false"
        )

    def chat_confirm(self, request_id: str) -> str:
        rec = self.requests[request_id]
        before = self.balance
        rec.chat_confirmed = True
        if self.balance != before or rec.status != "needs_approval":
            raise SystemExit("FAIL chat confirm moved money")
        policy = str(self.policy_allows_unapproved_send).lower()
        return (
            f"chat_confirm id={rec.id} chat_confirmed=true status={rec.status} "
            f"balance={self.balance} moved=false "
            f"policy_allows_unapproved_send={policy}"
        )

    def approve(self, role: str, request_id: str) -> str:
        rec = self.requests[request_id]
        if role != "mercury":
            return (
                f"approve role={role} id={rec.id} ok=false "
                f"reason=mercury_role_required status={rec.status} "
                f"balance={self.balance}"
            )
        if rec.status != "needs_approval":
            return (
                f"approve role={role} id={rec.id} ok=false reason=not_pending "
                f"status={rec.status} balance={self.balance}"
            )
        rec.status = "sent"
        self.balance -= rec.amount
        return (
            f"approve role={role} id={rec.id} ok=true status={rec.status} "
            f"balance={self.balance} moved=true"
        )

    def decline(self, role: str, request_id: str) -> str:
        rec = self.requests[request_id]
        if role != "mercury":
            return (
                f"decline role={role} id={rec.id} ok=false "
                f"reason=mercury_role_required status={rec.status} "
                f"balance={self.balance}"
            )
        if rec.status != "needs_approval":
            raise SystemExit("FAIL decline status")
        before = self.balance
        rec.status = "declined"
        if self.balance != before:
            raise SystemExit("FAIL decline moved money")
        return (
            f"decline role={role} id={rec.id} ok=true status={rec.status} "
            f"balance={self.balance} moved=false"
        )

    def update_note(self, role: str, txn: str, note: str) -> str:
        if role != "chat":
            raise SystemExit("FAIL update_note role")
        if "transactions:update" not in self.scopes:
            raise SystemExit("FAIL update scope")
        previous = self.notes.get(txn, "")
        self.notes[txn] = note
        overwritten = str(previous != "").lower()
        shown_previous = previous if previous else "empty"
        return (
            f"update_note role={role} txn={txn} note={note} "
            f"previous={shown_previous} pending=false applied=true "
            f"overwritten={overwritten}"
        )

    def request_transfer(self, role: str) -> str:
        if "transfers:request" in self.scopes:
            raise SystemExit("FAIL transfer scope should be absent")
        return (
            f"request_transfer role={role} ok=false reason=scope_missing "
            f"scope=transfers:request balance={self.balance}"
        )


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def main() -> None:
    ledger = Ledger()

    def emit(line: str) -> str:
        print(line)
        return line

    emit(
        "policy_allows_unapproved_send="
        + str(ledger.policy_allows_unapproved_send).lower()
    )
    line = emit(ledger.request_payment("chat", "Acme", 500))
    require("status=needs_approval" in line and "balance=1000" in line, "create")
    require(ledger.balance == 1000, "balance after request")
    require(len(ledger.requests) == 1, "one pending")

    line = emit(ledger.chat_confirm("pay_1"))
    require(ledger.requests["pay_1"].chat_confirmed, "confirmed flag")
    require(ledger.requests["pay_1"].status == "needs_approval", "still pending")
    require(ledger.balance == 1000, "confirm balance")
    require("moved=false" in line, "confirm moved flag")

    line = emit(ledger.approve("chat", "pay_1"))
    require("ok=false" in line and "mercury_role_required" in line, "chat approve")
    require(ledger.balance == 1000, "chat approve balance")
    require(ledger.requests["pay_1"].status == "needs_approval", "chat left pending")

    line = emit(ledger.request_payment("chat", "Acme", 500, uncertain_retry=True))
    require("created=false" in line and "id=pay_1" in line, "retry")
    require(len(ledger.requests) == 1, "retry did not create")

    line = emit(ledger.approve("mercury", "pay_1"))
    require("status=sent" in line and "balance=500" in line and "moved=true" in line, "sent")
    require(ledger.balance == 500, "balance sent")

    line = emit(ledger.approve("mercury", "pay_1"))
    require("reason=not_pending" in line and "balance=500" in line, "double approve")
    require(ledger.balance == 500, "double approve balance")

    queued = len(ledger.requests)
    line = emit(ledger.update_note("chat", "txn_1", "Annual renewal"))
    require(ledger.notes["txn_1"] == "Annual renewal", "note")
    require("pending=false" in line and "applied=true" in line, "immediate")
    require(len(ledger.requests) == queued, "note did not queue")

    line = emit(ledger.update_note("chat", "txn_1", "Renewed"))
    require("overwritten=true" in line, "overwrite")
    require(ledger.notes["txn_1"] == "Renewed", "new note")
    require(len(ledger.requests) == queued, "overwrite did not queue")

    line = emit(ledger.request_transfer("chat"))
    require("scope_missing" in line and "transfers:request" in line, "transfer scope")
    require(ledger.balance == 500, "transfer balance")

    line = emit(ledger.request_payment("chat", "Northwind", 100))
    require("id=pay_2" in line and "balance=500" in line and "moved=false" in line, "second")
    require(ledger.requests["pay_2"].status == "needs_approval", "pay_2 pending")

    line = emit(ledger.decline("chat", "pay_2"))
    require("ok=false" in line and "mercury_role_required" in line, "chat decline")
    require(ledger.requests["pay_2"].status == "needs_approval", "decline left pending")
    require(ledger.balance == 500, "chat decline balance")

    line = emit(ledger.decline("mercury", "pay_2"))
    require("status=declined" in line and "moved=false" in line, "decline")
    require(ledger.balance == 500, "decline balance")

    print("checks passed")


if __name__ == "__main__":
    main()
