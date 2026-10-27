#!/usr/bin/env python3
"""Show two public request shapes for agentic retrieval. No AWS calls.

gateway_tools_call.json follows the AgentCore Gateway tools/call example:
the agent sends messages only. The knowledge base id is bound on the target.

agentic_retrieve_request.json follows the AgenticRetrieveStream API example,
with two placeholder retrievers so a direct call can route by description.
The ids are not real. Nothing in this script opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def main() -> None:
    gateway = load("gateway_tools_call.json")
    raw = load("agentic_retrieve_request.json")

    arguments = gateway["params"]["arguments"]
    if set(arguments) != {"messages"}:
        raise SystemExit(f"gateway arguments should be only messages, got {sorted(arguments)}")
    if "knowledgeBaseId" in json.dumps(gateway):
        raise SystemExit("gateway tools/call should not carry knowledgeBaseId")
    if gateway["method"] != "tools/call":
        raise SystemExit("gateway method should be tools/call")

    retrievers = raw["retrievers"]
    if len(retrievers) != 2:
        raise SystemExit(f"expected 2 retrievers, got {len(retrievers)}")
    ids = []
    for retriever in retrievers:
        if not retriever.get("description"):
            raise SystemExit("each retriever needs a description")
        ids.append(retriever["configuration"]["knowledgeBase"]["knowledgeBaseId"])
    model_type = raw["agenticRetrieveConfiguration"]["foundationModelType"]
    if model_type != "MANAGED":
        raise SystemExit(f"example uses MANAGED, got {model_type}")

    print(f"gateway tools/call arguments: {', '.join(sorted(arguments))}")
    print("gateway carries knowledgeBaseId: no")
    print(f"gateway tool name: {gateway['params']['name']}")
    print(f"raw retrievers: {len(retrievers)}")
    print(f"raw retriever ids: {', '.join(ids)}")
    print(f"raw foundationModelType: {model_type}")
    print("who picks the KB on the gateway path: the tool name, bound on the target")
    print("who picks the KB on the direct API path: retrievers[].description and knowledgeBaseId")


if __name__ == "__main__":
    main()
