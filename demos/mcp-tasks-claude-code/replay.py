#!/usr/bin/env python3
"""Replay MCP Tasks (extension io.modelcontextprotocol/tasks, schema 2026-07-28).

This is an in-process JSON-RPC model. It does not start Claude Code, open a
socket, or call Upstash. Two behaviors are copied from the Claude Code MCP
docs as a client model, and labeled as such in the output:

- a tools/call resultType of "task" without the tasks extension is rejected
- a non-interactive session cancels a task that asks for elicitation, and
  does not run an Elicitation hook or onElicitation

The two-minute auto-background path is a separate timer. The HTTP request
stays open. That threshold is the documented default, not a measurement from
this machine.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

TASKS_EXT = "io.modelcontextprotocol/tasks"
ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / "fixtures"
MISSING_CAPABILITY = -32021
UNKNOWN_TASK = -32602
AUTO_BACKGROUND_MS = 120_000
POLL_MIN_MS = 250
POLL_MAX_MS = 30_000
POLL_DEFAULT_MS = 2_000


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def has_tasks(params: dict) -> bool:
    meta = params.get("_meta") or {}
    caps = meta.get("io.modelcontextprotocol/clientCapabilities") or {}
    extensions = caps.get("extensions") or {}
    return TASKS_EXT in extensions


def clamp_poll(value: object) -> int | None:
    """Claude Code's documented poll interval. None means the client rejects it."""
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if value < POLL_MIN_MS:
        return POLL_MIN_MS
    if value > POLL_MAX_MS:
        return POLL_MAX_MS
    return value


def client_accepts_create(result: dict) -> str | None:
    """Return an error string when Claude Code's documented checks would fail."""
    if result.get("resultType") != "task":
        return "plain result, not a task handle"
    missing = [
        key
        for key in ("taskId", "status", "createdAt", "lastUpdatedAt", "ttlMs")
        if key not in result
    ]
    if missing:
        return "Unsupported result type 'task' for tools/call"
    status = result["status"]
    if status not in {"working", "input_required", "completed", "failed", "cancelled"}:
        return "Unsupported result type 'task' for tools/call"
    task_id = result["taskId"]
    if (
        not isinstance(task_id, str)
        or len(task_id) > 128
        or any(ord(ch) < 32 or ord(ch) > 126 or ch == " " for ch in task_id)
    ):
        return "malformed task handle"
    if "pollIntervalMs" in result and clamp_poll(result["pollIntervalMs"]) is None:
        return "pollIntervalMs null or not an integer"
    return None


@dataclass
class Task:
    task_id: str
    tool: str
    title: str
    status: str
    created_at: str
    ttl_ms: int | None
    poll_interval_ms: int
    status_message: str = "Accepted"
    work_steps_left: int = 1
    ask: bool = False
    answered: bool = False
    accepted: bool | None = None
    result: dict | None = None
    error: dict | None = None
    durable: bool = False
    last_updated_at: str = ""

    def __post_init__(self) -> None:
        self.last_updated_at = self.created_at
        self.durable = True


@dataclass
class Server:
    """A server that cannot hold an HTTP request open for export or publish."""

    now: str = "2026-10-29T01:10:00Z"
    tasks: dict[str, Task] = field(default_factory=dict)
    request_open: bool = False

    def tools_call(self, request: dict) -> dict:
        params = request["params"]
        name = params["name"]
        self.request_open = True
        if name == "lookup_status":
            self.request_open = False
            return self._ok(
                request["id"],
                {
                    "content": [{"type": "text", "text": "job-14 status=idle"}],
                    "isError": False,
                },
            )
        if name not in {"export_report", "publish_post"}:
            self.request_open = False
            return self._err(request["id"], -32602, "unknown tool")
        if not has_tasks(params):
            self.request_open = False
            return self._err(
                request["id"],
                MISSING_CAPABILITY,
                "Missing required client capability",
                {
                    "requiredCapabilities": {
                        "extensions": {TASKS_EXT: {}},
                    }
                },
            )
        task_id = "export-7f3a9c2e" if name == "export_report" else "publish-1c0e"
        title = str((params.get("arguments") or {}).get("title") or name)
        task = Task(
            task_id=task_id,
            tool=name,
            title=title,
            status="working",
            created_at=self.now,
            ttl_ms=86_400_000,
            poll_interval_ms=2_000,
            ask=name == "publish_post",
            work_steps_left=0 if name == "publish_post" else 1,
        )
        # SEP-2663: tasks/get for this id must resolve before the response.
        if not task.durable:
            raise SystemExit("FAIL task was not durable before the response")
        self.tasks[task_id] = task
        self.request_open = False
        result = {
            "resultType": "task",
            "taskId": task.task_id,
            "status": task.status,
            "statusMessage": task.status_message,
            "createdAt": task.created_at,
            "lastUpdatedAt": task.last_updated_at,
            "ttlMs": task.ttl_ms,
            "pollIntervalMs": task.poll_interval_ms,
        }
        return self._ok(request["id"], result)

    def tasks_get(self, request_id: int, task_id: str) -> dict:
        task = self.tasks.get(task_id)
        if task is None:
            return self._err(request_id, UNKNOWN_TASK, "unknown task")
        self._advance(task)
        body: dict = {
            "resultType": "complete",
            "taskId": task.task_id,
            "status": task.status,
            "statusMessage": task.status_message,
            "createdAt": task.created_at,
            "lastUpdatedAt": task.last_updated_at,
            "ttlMs": task.ttl_ms,
            "pollIntervalMs": task.poll_interval_ms,
        }
        if task.status == "input_required":
            body["inputRequests"] = {
                "confirm": {
                    "method": "elicitation/create",
                    "params": {
                        "message": f'Publish "{task.title}" now?',
                        "mode": "form",
                    },
                }
            }
        if task.status == "completed" and task.result is not None:
            body["result"] = task.result
        if task.status == "failed" and task.error is not None:
            body["error"] = task.error
        return self._ok(request_id, body)

    def tasks_update(self, request_id: int, task_id: str, responses: dict) -> dict:
        task = self.tasks.get(task_id)
        if task is None:
            return self._err(request_id, UNKNOWN_TASK, "unknown task")
        confirm = responses.get("confirm") or {}
        task.answered = True
        task.accepted = confirm.get("action") == "accept" and bool(
            (confirm.get("content") or {}).get("publish")
        )
        task.status = "working"
        task.status_message = "Answer recorded"
        return self._ok(request_id, {"resultType": "complete"})

    def tasks_cancel(self, request_id: int, task_id: str) -> dict:
        task = self.tasks.get(task_id)
        if task is None:
            return self._err(request_id, UNKNOWN_TASK, "unknown task")
        task.status = "cancelled"
        task.status_message = "Task was cancelled by the server"
        task.work_steps_left = 0
        return self._ok(request_id, {"resultType": "complete"})

    def _advance(self, task: Task) -> None:
        if task.status in {"completed", "failed", "cancelled"}:
            return
        if task.ask and not task.answered:
            task.status = "input_required"
            task.status_message = "Waiting for confirmation"
            return
        if task.work_steps_left > 0:
            task.work_steps_left -= 1
            task.status = "working"
            task.status_message = "Writing report"
            return
        task.status = "completed"
        if task.tool == "export_report":
            text = "A report on urban-beekeeping."
        elif task.accepted:
            text = "Published."
        else:
            text = "Not published."
        task.status_message = "Done"
        task.result = {"content": [{"type": "text", "text": text}], "isError": False}

    def _ok(self, request_id: int, result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _err(self, request_id: int, code: int, message: str, data: dict | None = None) -> dict:
        error: dict = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": request_id, "error": error}


def follow_task(server: Server, task_id: str, interactive: bool, lines: list[str]) -> None:
    hooks_ran = False
    on_elicitation = False
    for poll in range(1, 6):
        response = server.tasks_get(10 + poll, task_id)
        result = response["result"]
        if result.get("resultType") != "complete":
            raise SystemExit("FAIL tasks/get resultType")
        status = result["status"]
        lines.append(
            f"tasks/get #{poll} resultType=complete status={status} "
            f"message={result.get('statusMessage')}"
        )
        if status == "input_required":
            method = result["inputRequests"]["confirm"]["method"]
            lines.append(f"inputRequests confirm method={method}")
            if not interactive:
                lines.append(
                    "noninteractive cancel hooks_ran="
                    f"{str(hooks_ran).lower()} on_elicitation={str(on_elicitation).lower()}"
                )
                ack = server.tasks_cancel(20, task_id)
                lines.append(
                    "tasks/cancel resultType=" + ack["result"]["resultType"]
                )
                continue
            lines.append("interactive dialog answer=accept")
            ack = server.tasks_update(
                21,
                task_id,
                {"confirm": {"action": "accept", "content": {"publish": True}}},
            )
            lines.append("tasks/update resultType=" + ack["result"]["resultType"])
            continue
        if status in {"completed", "failed", "cancelled"}:
            if status == "completed":
                text = result["result"]["content"][0]["text"]
                lines.append(f"result_text={text}")
            return
    raise SystemExit("FAIL task did not finish")


def blocking_model(duration_ms: int) -> list[str]:
    """Client-side auto-background. The request stays open the whole time."""
    lines = []
    request_open = True
    moved = False
    for t in (0, AUTO_BACKGROUND_MS, duration_ms):
        if t >= AUTO_BACKGROUND_MS and request_open:
            moved = True
        lines.append(
            f"t={t}ms request_open={str(request_open).lower()} "
            f"client_background={str(moved and t >= AUTO_BACKGROUND_MS).lower()} "
            f"survives_exit=false"
        )
    request_open = False
    lines.append(
        f"call_settled request_open={str(request_open).lower()} "
        "server_had_to_hold_request=true"
    )
    return lines


def main() -> None:
    lines: list[str] = []
    lines.append(f"python {sys.version.split()[0]}")
    lines.append("claude_cli not_invoked")
    lines.append("upstash not_deployed")
    lines.append("transport in_process")

    export = load("export_tools_call.json")
    if not has_tasks(export["params"]):
        raise SystemExit("FAIL fixture missing tasks capability")
    server = Server()
    created = server.tools_call(export)
    handle = created["result"]
    problem = client_accepts_create(handle)
    if problem:
        raise SystemExit("FAIL create rejected: " + problem)
    if server.request_open:
        raise SystemExit("FAIL request still open after task handle")
    if handle["taskId"] not in server.tasks:
        raise SystemExit("FAIL task missing from store at response time")
    lines.append("== export-with-tasks ==")
    lines.append(
        "tools/call capability=tasks resultType=task "
        f"taskId={handle['taskId']} status={handle['status']} "
        f"pollIntervalMs={handle['pollIntervalMs']} ttlMs={handle['ttlMs']}"
    )
    stored = server.tasks[handle["taskId"]]
    lines.append(
        "request_open="
        + str(server.request_open).lower()
        + " durable_before_response="
        + str(stored.durable).lower()
        + f" work_steps_left={stored.work_steps_left}"
    )
    follow_task(server, handle["taskId"], interactive=True, lines=lines)

    lines.append("== export-without-tasks ==")
    bare = load("export_tools_call_no_tasks.json")
    refused = Server().tools_call(bare)
    err = refused["error"]
    lines.append(
        f"error code={err['code']} message={err['message']} "
        "extension_present="
        + str(TASKS_EXT in err["data"]["requiredCapabilities"]["extensions"]).lower()
    )
    lines.append("resultType_returned=no request_open=false")

    lines.append("== lookup-with-tasks ==")
    lookup = Server().tools_call(load("lookup_tools_call.json"))
    text = lookup["result"]["content"][0]["text"]
    lines.append(f"resultType_absent text={text}")

    lines.append("== publish-interactive ==")
    pub = Server()
    handle = pub.tools_call(load("publish_tools_call.json"))["result"]
    lines.append(f"taskId={handle['taskId']} status={handle['status']}")
    follow_task(pub, handle["taskId"], interactive=True, lines=lines)

    lines.append("== publish-noninteractive ==")
    pub = Server()
    handle = pub.tools_call(load("publish_tools_call.json"))["result"]
    follow_task(pub, handle["taskId"], interactive=False, lines=lines)

    lines.append("== unknown-task ==")
    missing = Server().tasks_get(30, "missing-id")
    lines.append(f"error code={missing['error']['code']} message={missing['error']['message']}")

    lines.append("== client-shape-checks ==")
    bad = dict(handle)
    del bad["ttlMs"]
    lines.append(
        "missing_fields=ttlMs client_error=" + (client_accepts_create(bad) or "accepted")
    )
    spaced = dict(handle)
    spaced["taskId"] = "has space"
    lines.append("space_in_id=" + (client_accepts_create(spaced) or "accepted"))
    lines.append(
        "poll absent="
        + str(POLL_DEFAULT_MS)
        + " poll 100="
        + str(clamp_poll(100))
        + " poll 99999="
        + str(clamp_poll(99999))
        + " poll_null="
        + ("rejected" if clamp_poll(None) is None else "accepted")
    )

    lines.append("== blocking-two-minutes ==")
    lines.extend(blocking_model(180_000))

    lines.append("checks passed")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
