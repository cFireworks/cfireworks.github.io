#!/usr/bin/env python3
"""Miniature of a capture proxy that records engine token ids.

This is not OpenEnv. It implements the slice checked on 2026-10-09 against
OpenEnv main b6fa103 and TRL main ed8cc2f:

- the proxy copies ``prompt_token_ids`` and ``token_ids`` from the engine
- a harness ``top_p`` of 0.8 is forwarded as 1.0, with ``return_token_ids``
- an unknown API key is rejected
- turn k+1 is the child of turn k only when k's prompt+completion is an
  exact prefix of k+1's prompt ids
- a toolless call is left out of the training entries when another call
  in the same rollout carried tools
- the trainer row uses ``loss_mask[len(prompt):]`` as the completion mask

The reward block uses the coefficients in
``examples/async_grpo_harbor/async_grpo_harbor.py`` on that TRL commit
(``W_TOOL_EFFICIENCY = 0.3``, ``TOOL_BUDGET = 15``), not the 0.1 cap in the
multi-harness guide.
"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

MERGE = {("t", "e"): 7}
SESSION = "rollout-1"


def require(cond: bool, message: str) -> None:
    if not cond:
        raise SystemExit(f"FAIL {message}")


def engine_ids(text: str) -> list[int]:
    """The mock engine's private encoding. The proxy never calls this."""
    ids = [1]
    i = 0
    while i < len(text):
        pair = (text[i], text[i + 1] if i + 1 < len(text) else "")
        if pair in MERGE:
            ids.append(MERGE[pair])
            i += 2
            continue
        ids.append(ord(text[i]) + 32)
        i += 1
    return ids


def body_ids(text: str) -> list[int]:
    return engine_ids(text)[1:]


def naive_char_ids(text: str) -> list[int]:
    """A local re-encode that forgets the BOS id and the 'te' merge."""
    return [ord(char) + 32 for char in text]


def message_text(messages: list[dict]) -> str:
    return "".join(
        message["content"] for message in messages if isinstance(message.get("content"), str)
    )


class EngineState:
    def __init__(self) -> None:
        self.seen: list[dict] = []

    def complete(self, body: dict) -> dict:
        self.seen.append(
            {
                "top_p": body.get("top_p"),
                "return_token_ids": body.get("return_token_ids"),
                "logprobs": body.get("logprobs"),
                "top_logprobs": body.get("top_logprobs"),
            }
        )
        text = message_text(body.get("messages") or [])
        assistant = "ok" if len(self.seen) == 1 else "done"
        completion = body_ids(assistant)
        return {
            "prompt_token_ids": engine_ids(text),
            "choices": [
                {
                    "message": {"role": "assistant", "content": assistant},
                    "finish_reason": "stop",
                    "token_ids": completion,
                    "logprobs": {
                        "content": [
                            {"token": f"token_id:{token}", "logprob": -0.25 * i}
                            for i, token in enumerate(completion, start=1)
                        ]
                    },
                }
            ],
        }


ENGINE = EngineState()
ENGINE_URL = ""


def write_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    raw = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length == 0:
        return {}
    return json.loads(handler.rfile.read(length))


class EngineHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        write_json(self, 200, ENGINE.complete(read_json(self)))

    def log_message(self, fmt: str, *args) -> None:
        return


class Node:
    def __init__(self, body: dict, response: dict) -> None:
        choice = response["choices"][0]
        self.prompt = list(response["prompt_token_ids"])
        self.completion = list(choice["token_ids"])
        self.logprobs = [item["logprob"] for item in choice["logprobs"]["content"]]
        self.messages = body.get("messages") or []
        self.n_tools = len(body.get("tools") or [])
        self.loss_mask = [0] * len(self.prompt) + [1] * len(self.completion)

    def end(self) -> list[int]:
        return self.prompt + self.completion


class ProxyState:
    def __init__(self) -> None:
        self.nodes: list[Node] = []

    def parent(self, index: int) -> int | None:
        node = self.nodes[index]
        best: int | None = None
        best_len = 0
        for earlier in range(index):
            end = self.nodes[earlier].end()
            if len(self.nodes[earlier].prompt) >= len(node.prompt):
                continue
            if len(end) > len(node.prompt) or len(end) <= best_len:
                continue
            if node.prompt[: len(end)] == end:
                best = earlier
                best_len = len(end)
        return best

    def roots(self) -> list[int]:
        return [i for i in range(len(self.nodes)) if self.parent(i) is None]

    def training_indexes(self) -> list[int]:
        """Drop toolless roots when some other call in the rollout had tools."""
        if not any(node.n_tools for node in self.nodes):
            return list(range(len(self.nodes)))
        kept: list[int] = []
        children: dict[int, list[int]] = {i: [] for i in range(len(self.nodes))}
        for i in range(len(self.nodes)):
            parent = self.parent(i)
            if parent is not None:
                children[parent].append(i)
        for root in self.roots():
            path = []
            stack = [root]
            while stack:
                current = stack.pop()
                path.append(current)
                stack.extend(children[current])
            if any(self.nodes[i].n_tools for i in path):
                kept.extend(sorted(path))
        return sorted(set(kept))


PROXY = ProxyState()


class ProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path == "/sessions":
            write_json(
                self,
                200,
                {
                    "session_id": SESSION,
                    "rollout_type": "train",
                    "capture_level": "tokens",
                },
            )
            return
        if self.path != "/v1/chat/completions":
            write_json(self, 404, {"error": "not found"})
            return
        token = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        if token != SESSION:
            write_json(
                self,
                401,
                {"error": {"message": "unknown API key; register a session via POST /sessions"}},
            )
            return
        body = read_json(self)
        # The harness asked for a truncated distribution. Training capture
        # forwards the no-op value instead, and asks the engine for ids.
        forwarded = dict(body)
        forwarded["top_p"] = 1.0
        forwarded["logprobs"] = True
        forwarded["top_logprobs"] = 0
        forwarded["return_token_ids"] = True
        request = Request(
            ENGINE_URL + "/v1/chat/completions",
            data=json.dumps(forwarded).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read())
        PROXY.nodes.append(Node(body, payload))
        write_json(self, 200, payload)

    def do_GET(self) -> None:
        if self.path != f"/sessions/{SESSION}/trace_entries":
            write_json(self, 404, {"error": "not found"})
            return
        entries = []
        for index in PROXY.training_indexes():
            node = PROXY.nodes[index]
            entries.append(
                {
                    "prompt_token_ids": node.prompt,
                    "completion_token_ids": node.completion,
                    "per_token_logps": node.logprobs,
                    "loss_mask": node.loss_mask,
                    "request": {"messages": node.messages},
                }
            )
        write_json(
            self,
            200,
            {
                "n_turns": len(PROXY.nodes),
                "n_roots": len(PROXY.roots()),
                "entries": entries,
            },
        )

    def log_message(self, fmt: str, *args) -> None:
        return


def post(url: str, payload: dict, session: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if session is not None:
        headers["Authorization"] = f"Bearer {session}"
    request = Request(url, data=json.dumps(payload).encode(), headers=headers)
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except Exception as exc:
        if not hasattr(exc, "code"):
            raise
        return int(exc.code), json.loads(exc.read())


def completion_mask(prompt: list[int], completion: list[int], loss_mask: list[int]) -> list[int]:
    if len(loss_mask) != len(prompt) + len(completion):
        raise ValueError("loss_mask must cover prompt plus completion")
    if any(bit not in (0, 1) for bit in loss_mask):
        raise ValueError("loss_mask bits must be 0 or 1")
    if any(loss_mask[: len(prompt)]):
        raise ValueError("prompt tokens must remain context")
    return loss_mask[len(prompt) :]


def trained_ids(completion: list[int], output_mask: list[int]) -> list[int]:
    return [token for token, bit in zip(completion, output_mask) if bit == 1]


def harbor_reward(correctness: float | None, n_tools: int | None) -> float | None:
    """Same shape as ``harbor_reward`` in the TRL Harbor example."""
    if correctness is None:
        return None
    reward = float(correctness)
    if n_tools is None or correctness < 1.0:
        return reward
    efficiency = max(0.0, min(1.0, 1.0 - n_tools / 15.0))
    return reward + 0.3 * efficiency


def serve(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> None:
    global ENGINE_URL
    print(f"python {sys.version.split()[0]}")
    engine = serve(EngineHandler)
    proxy = serve(ProxyHandler)
    ENGINE_URL = f"http://127.0.0.1:{engine.server_address[1]}"
    proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"

    minted = post(proxy_url + "/sessions", {})[1]
    print(
        "session",
        minted["session_id"],
        "rollout_type",
        minted["rollout_type"],
        "level",
        minted["capture_level"],
    )
    status, rejected = post(
        proxy_url + "/v1/chat/completions",
        {"model": "toy", "messages": [{"role": "user", "content": "no"}]},
        session="not-a-session",
    )
    print("unknown_key", status, rejected["error"]["message"])
    require(status == 401, "unknown key was accepted")

    tools = [{"type": "function", "function": {"name": "bash"}}]
    status, first = post(
        proxy_url + "/v1/chat/completions",
        {
            "model": "toy",
            "top_p": 0.8,
            "messages": [{"role": "user", "content": "fix the test"}],
            "tools": tools,
        },
        session=SESSION,
    )
    require(status == 200, "first completion failed")
    assistant = first["choices"][0]["message"]["content"]
    post(
        proxy_url + "/v1/chat/completions",
        {
            "model": "toy",
            "top_p": 0.8,
            "messages": [
                {"role": "user", "content": "fix the test"},
                {"role": "assistant", "content": assistant},
                {"role": "tool", "content": "AssertionError"},
            ],
            "tools": tools,
        },
        session=SESSION,
    )
    post(
        proxy_url + "/v1/chat/completions",
        {
            "model": "toy",
            "messages": [{"role": "user", "content": "fix the tests"}],
            "tools": tools,
        },
        session=SESSION,
    )
    post(
        proxy_url + "/v1/chat/completions",
        {"model": "toy", "messages": [{"role": "user", "content": "title"}]},
        session=SESSION,
    )

    print("engine_saw", json.dumps(ENGINE.seen, ensure_ascii=False))
    with urlopen(proxy_url + f"/sessions/{SESSION}/trace_entries", timeout=5) as response:
        document = json.loads(response.read())
    entries = document["entries"]
    print(
        "graph",
        f"n_turns={document['n_turns']}",
        f"n_roots={document['n_roots']}",
        f"n_entries={len(entries)}",
    )
    require(document["n_turns"] == 4, "title call was not recorded")
    require(document["n_roots"] == 3, "rewritten prompt was stitched onto the first chain")
    require(len(entries) == 3, "toolless call was trained")
    require(all(item["top_p"] == 1.0 for item in ENGINE.seen), "top_p was not rewritten")
    require(all(item["return_token_ids"] is True for item in ENGINE.seen), "ids were not requested")

    for index, entry in enumerate(entries):
        prompt = entry["prompt_token_ids"]
        completion = entry["completion_token_ids"]
        text = message_text(entry["request"]["messages"])
        output_mask = completion_mask(prompt, completion, entry["loss_mask"])
        print(
            f"turn {index} prompt={prompt} completion={completion} "
            f"logprobs={entry['per_token_logps']} trained={trained_ids(completion, output_mask)} "
            f"naive_equal={naive_char_ids(text) == prompt}"
        )
        require(len(entry["per_token_logps"]) == len(completion), "logprobs misaligned")
        require(naive_char_ids(text) != prompt, "naive re-encode matched the engine")

    extended = entries[1]["prompt_token_ids"]
    previous = entries[0]["prompt_token_ids"] + entries[0]["completion_token_ids"]
    print("turn1_extends_turn0", extended[: len(previous)] == previous)
    require(extended[: len(previous)] == previous, "continued turn was not an exact prefix")
    rewrite = entries[2]["prompt_token_ids"]
    print("rewrite_extends_turn0_end", rewrite[: len(previous)] == previous)
    require(rewrite[: len(previous)] != previous, "rewritten prompt was treated as a continuation")

    readme_prompt = [10, 11]
    readme_completion = [12, 13, 14]
    readme_mask = [0, 0, 1, 0, 1]
    readme_output = completion_mask(readme_prompt, readme_completion, readme_mask)
    print(
        "readme_mask",
        f"trained={trained_ids(readme_completion, readme_output)}",
        f"context={[token for token, bit in zip(readme_completion, readme_output) if bit == 0]}",
    )
    try:
        completion_mask([10, 11], [12, 13, 14], [1, 0, 1, 0, 1])
    except ValueError as exc:
        print("bad_mask", exc)
    else:
        raise SystemExit("FAIL prompt mask bit was accepted")

    samples = [
        ("wrong", 0.0, 2),
        ("correct_short", 1.0, 0),
        ("correct_at_budget", 1.0, 15),
        ("correct_3", 1.0, 3),
        ("correct_12", 1.0, 12),
        ("unscored", None, 1),
    ]
    print("reward_weight", 0.3, "tool_budget", 15)
    for name, correctness, n_tools in samples:
        value = harbor_reward(correctness, n_tools)
        rendered = "None" if value is None else f"{value:.4f}"
        print(f"reward {name} correctness={correctness} tools={n_tools} value={rendered}")

    print("checks passed")
    proxy.shutdown()
    engine.shutdown()


if __name__ == "__main__":
    main()
