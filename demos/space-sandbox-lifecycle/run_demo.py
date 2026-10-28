#!/usr/bin/env python3
"""Simulate SPACE sandbox lifecycle tiers. No network calls.

The transitions follow two public contracts, and they are not a SPACE client:

- Open-source architecture: pause keeps VM memory resident on the worker and
  is not a durable snapshot; suspend stores VM memory, runtime state, and the
  root filesystem, then releases the VM; wake returns either state to running.
- The 2026-07-15 design article: a disk snapshot rolls files back, a full
  checkpoint restores a paused VM, and a suspend snapshot is restorable only
  after every artifact has landed, possibly on another node.

``SHORT_HOLD_S`` is this demo's threshold. The six-hour idle suspend comes
from the architecture guide. Credentials stay in the control-plane vault.
"""

from __future__ import annotations

from dataclasses import dataclass, field


SHORT_HOLD_S = 15 * 60
IDLE_SUSPEND_S = 6 * 60 * 60

ECW_TO_SPACE = {
    "pause": "suspend",
    "resume": "restore",
}


def choose_hold(wait_s: int, node_stable: bool) -> str:
    """Resident pause only for a short wait on a node that stays up."""
    if wait_s <= SHORT_HOLD_S and node_stable:
        return "pause"
    return "suspend"


def choose_rollback(files_wrong: bool, memory_worth_keeping: bool) -> str:
    """Keep a full checkpoint when process memory matters; else roll files back."""
    if memory_worth_keeping:
        return "full"
    if files_wrong:
        return "disk"
    return "none"


@dataclass
class Sandbox:
    state: str
    node: str | None
    memory: dict
    disk: dict
    op_done: bool = False
    disk_snap: dict | None = None
    full_snap: dict | None = None


@dataclass
class Plane:
    sandboxes: dict[str, Sandbox] = field(default_factory=dict)
    ops: dict[str, tuple[str, str]] = field(default_factory=dict)
    store: dict[str, dict] = field(default_factory=dict)
    vault: dict[str, str] = field(default_factory=lambda: {"api_token": "mgmt-not-in-guest"})
    seq: int = 0

    def create(self, key: str) -> tuple[str, str]:
        cached = self.ops.get(key)
        if cached is not None:
            return cached
        self.seq += 1
        sandbox_id = f"sbx_{self.seq}"
        operation_id = f"op_{self.seq}"
        self.sandboxes[sandbox_id] = Sandbox(
            state="accepted",
            node=None,
            memory={},
            disk={},
        )
        self.ops[key] = (sandbox_id, operation_id)
        return sandbox_id, operation_id

    def finish_create(self, sandbox_id: str, node: str = "node-a") -> None:
        sandbox = self.sandboxes[sandbox_id]
        sandbox.state = "running"
        sandbox.node = node
        sandbox.op_done = True

    def run_command(self, sandbox_id: str, memory: dict, disk: dict) -> None:
        sandbox = self.sandboxes[sandbox_id]
        if sandbox.state != "running" or not sandbox.op_done:
            raise RuntimeError("not ready")
        sandbox.memory = dict(memory)
        sandbox.disk = dict(disk)
        if "api_token" in sandbox.memory or "api_token" in sandbox.disk:
            raise RuntimeError("credential entered the guest")

    def pause(self, sandbox_id: str) -> None:
        sandbox = self.sandboxes[sandbox_id]
        if sandbox.state != "running":
            raise RuntimeError(f"cannot pause from {sandbox.state}")
        sandbox.state = "paused"

    def suspend(self, sandbox_id: str, complete: bool) -> None:
        sandbox = self.sandboxes[sandbox_id]
        if sandbox.state != "running":
            raise RuntimeError(f"cannot suspend from {sandbox.state}")
        self.store[sandbox_id] = {
            "memory": dict(sandbox.memory),
            "disk": dict(sandbox.disk),
            "complete": complete,
        }
        sandbox.memory = {}
        sandbox.disk = {}
        sandbox.node = None
        sandbox.state = "suspended"

    def wake(self, sandbox_id: str, node: str) -> None:
        sandbox = self.sandboxes[sandbox_id]
        if sandbox.state == "paused":
            if sandbox.node is None:
                raise RuntimeError("paused sandbox lost its node")
            sandbox.state = "running"
            return
        if sandbox.state == "suspended":
            snapshot = self.store.get(sandbox_id)
            if snapshot is None or not snapshot["complete"]:
                raise RuntimeError("snapshot is not restorable")
            sandbox.memory = dict(snapshot["memory"])
            sandbox.disk = dict(snapshot["disk"])
            sandbox.node = node
            sandbox.state = "running"
            return
        raise RuntimeError(f"cannot wake from {sandbox.state}")

    def lose_node(self, node: str) -> None:
        for sandbox in self.sandboxes.values():
            if sandbox.node == node and sandbox.state == "paused":
                sandbox.node = None
                sandbox.memory = {}
                sandbox.disk = {}

    def capture_disk(self, sandbox_id: str) -> None:
        sandbox = self.sandboxes[sandbox_id]
        sandbox.disk_snap = dict(sandbox.disk)

    def capture_full(self, sandbox_id: str) -> None:
        sandbox = self.sandboxes[sandbox_id]
        sandbox.full_snap = {
            "memory": dict(sandbox.memory),
            "disk": dict(sandbox.disk),
        }

    def rollback_disk(self, sandbox_id: str) -> None:
        sandbox = self.sandboxes[sandbox_id]
        if sandbox.disk_snap is None:
            raise RuntimeError("no disk snapshot")
        sandbox.disk = dict(sandbox.disk_snap)

    def restore_full(self, sandbox_id: str) -> None:
        sandbox = self.sandboxes[sandbox_id]
        if sandbox.full_snap is None:
            raise RuntimeError("no full checkpoint")
        sandbox.memory = dict(sandbox.full_snap["memory"])
        sandbox.disk = dict(sandbox.full_snap["disk"])
        sandbox.state = "running"

    def delete(self, sandbox_id: str) -> None:
        sandbox = self.sandboxes[sandbox_id]
        sandbox.state = "deleted"
        sandbox.memory = {}
        sandbox.disk = {}
        sandbox.node = None

    def idle(self, sandbox_id: str, idle_s: int, accessed: bool) -> None:
        sandbox = self.sandboxes[sandbox_id]
        if sandbox.state == "running" and not accessed and idle_s >= IDLE_SUSPEND_S:
            self.suspend(sandbox_id, complete=True)


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def guest_has_token(sandbox: Sandbox) -> bool:
    blob = str(sandbox.memory) + str(sandbox.disk) + str(sandbox.disk_snap) + str(sandbox.full_snap)
    return "mgmt-not-in-guest" in blob


def main() -> None:
    lines: list[str] = []

    def note(text: str) -> None:
        lines.append(text)

    require(choose_hold(5 * 60, True) == "pause", "short stable wait")
    require(choose_hold(5 * 60, False) == "suspend", "short unstable wait")
    require(choose_hold(2 * 60 * 60, True) == "suspend", "long wait")
    require(choose_rollback(True, False) == "disk", "files only")
    require(choose_rollback(True, True) == "full", "memory worth keeping")
    require(choose_rollback(False, False) == "none", "nothing to undo")
    require(ECW_TO_SPACE["pause"] == "suspend", "ecw pause")
    require(ECW_TO_SPACE["resume"] == "restore", "ecw resume")
    note("hold 5min/stable=pause 5min/unstable=suspend 2h/stable=suspend")
    note("rollback files=disk files+memory=full neither=none")
    note("ecw pause=suspend resume=restore")

    plane = Plane()
    sandbox_id, operation_id = plane.create("create-1")
    again_id, again_op = plane.create("create-1")
    other_id, _other_op = plane.create("create-2")
    require((sandbox_id, operation_id) == (again_id, again_op), "idempotency key")
    require(other_id != sandbox_id, "new key")
    require(plane.sandboxes[sandbox_id].state == "accepted", "accepted is not running")
    try:
        plane.run_command(sandbox_id, {"parsed": 1}, {"report": "v0"})
    except RuntimeError as exc:
        require(str(exc) == "not ready", "command before ready")
    else:
        raise SystemExit("FAIL command before ready was accepted")
    note(f"create {sandbox_id} {operation_id} replayed; command before running refused")

    plane.finish_create(sandbox_id)
    plane.run_command(sandbox_id, {"parsed": 12}, {"report": "v1"})
    sandbox = plane.sandboxes[sandbox_id]
    plane.capture_disk(sandbox_id)
    plane.capture_full(sandbox_id)
    plane.run_command(sandbox_id, {"parsed": 0}, {"report": "deleted"})
    plane.rollback_disk(sandbox_id)
    require(sandbox.disk == {"report": "v1"}, "disk file restored")
    require(sandbox.memory == {"parsed": 0}, "disk rollback leaves memory")
    note("disk rollback: file=v1 memory=0")

    plane.restore_full(sandbox_id)
    require(sandbox.memory == {"parsed": 12} and sandbox.disk == {"report": "v1"}, "full restore")
    note("full restore: file=v1 memory=12")

    plane.pause(sandbox_id)
    require(sandbox.state == "paused" and sandbox.node == "node-a", "pause stays resident")
    require(sandbox.memory == {"parsed": 12}, "pause keeps memory")
    plane.wake(sandbox_id, "node-b")
    require(sandbox.node == "node-a" and sandbox.state == "running", "wake stays on the paused node")
    note("pause/wake: still node-a memory=12")

    plane.pause(sandbox_id)
    plane.lose_node("node-a")
    try:
        plane.wake(sandbox_id, "node-a")
    except RuntimeError as exc:
        require(str(exc) == "paused sandbox lost its node", "lost node")
    else:
        raise SystemExit("FAIL paused sandbox woke after node loss")
    note("pause then lose node: wake refused")

    moved, _op = plane.create("move")
    plane.finish_create(moved)
    plane.run_command(moved, {"parsed": 12}, {"report": "v1"})
    plane.suspend(moved, complete=False)
    try:
        plane.wake(moved, "node-b")
    except RuntimeError as exc:
        require(str(exc) == "snapshot is not restorable", "partial upload")
    else:
        raise SystemExit("FAIL partial snapshot woke")
    note("suspend partial: wake refused")

    whole, _op = plane.create("whole")
    plane.finish_create(whole)
    plane.run_command(whole, {"parsed": 12}, {"report": "v1"})
    plane.suspend(whole, complete=True)
    stored = plane.store[whole]
    require(stored["complete"] and "mgmt-not-in-guest" not in str(stored), "snapshot has no token")
    plane.wake(whole, "node-b")
    restored = plane.sandboxes[whole]
    require(restored.state == "running" and restored.node == "node-b", "wake node")
    require(restored.memory == {"parsed": 12} and restored.disk == {"report": "v1"}, "wake payload")
    note("suspend complete: wake on node-b memory=12 file=v1")

    quiet, _op = plane.create("quiet")
    plane.finish_create(quiet, node="node-c")
    plane.run_command(quiet, {"parsed": 3}, {"report": "v1"})
    plane.idle(quiet, IDLE_SUSPEND_S - 1, accessed=False)
    require(plane.sandboxes[quiet].state == "running", "idle under six hours")
    plane.idle(quiet, IDLE_SUSPEND_S, accessed=False)
    require(plane.sandboxes[quiet].state == "suspended", "idle suspends")
    require(plane.sandboxes[quiet].node is None, "idle releases the node")
    plane.wake(quiet, "node-d")
    require(plane.sandboxes[quiet].memory == {"parsed": 3}, "idle snapshot kept memory")
    note("idle 6h: suspend then wake on node-d memory=3")

    doomed, _op = plane.create("doomed")
    plane.finish_create(doomed)
    plane.run_command(doomed, {"parsed": 1}, {"report": "unsynced"})
    plane.delete(doomed)
    require(plane.sandboxes[doomed].state == "deleted", "deleted")
    require(plane.sandboxes[doomed].disk == {}, "delete discards disk")
    note("delete: disk discarded")

    require(plane.vault["api_token"] == "mgmt-not-in-guest", "vault")
    require(not any(guest_has_token(item) for item in plane.sandboxes.values()), "guest token")
    note("credentials: vault only")

    print("\n".join(lines))
    print("checks passed")


if __name__ == "__main__":
    main()
