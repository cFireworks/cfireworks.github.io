#!/usr/bin/env python3
"""Local stand-in for OpenSandbox's public Credential Vault reads.

This process does not call OpenSandbox. Shapes follow the lifecycle models
at tag release-1.2.0-rc.2:

- CredentialVaultState: revision, credentials, bindings
- CredentialMetadata: name, sourceType, revision
- CredentialBindingMetadata: name, revision, match, auth
- CredentialAuthMetadata: type, and name only for the apiKey shape
- CredentialVaultMutationRequest: expectedRevision; credentials add/replace/delete

The fsb docstring on CredentialMetadata says the relay does not carry
per-record revisions, so each record's revision here is the vault revision
just read. Other backends track per-record revisions; this demo does not.

A paused subject is "sealed": vault mutations answer 409 and do not apply.
expectedRevision mismatch answers 412 and does not apply. Error bodies are
status only — the published error schema for those codes was not copied here.

422 handling follows server/opensandbox_server/main.py at the same tag:
validation errors drop input and ctx so a rejected body cannot echo a value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

SECRET = "demo-not-a-real-token"
FAKE_GUEST_KEY = "fake-key-inside-sandbox"
FORBIDDEN_KEYS = frozenset({"value", "source", "input", "ctx"})


@dataclass
class StoredCredential:
    name: str
    source_type: str
    value: str


@dataclass
class EgressVault:
    """Egress-held store. The value field never leaves public_state()."""

    revision: int = 0
    sealed: bool = False
    credentials: dict[str, StoredCredential] = field(default_factory=dict)
    binding_name: str = "example-api"
    binding_host: str = "api.example.com"

    def public_state(self) -> dict:
        revision = self.revision
        return {
            "revision": revision,
            "credentials": [
                {
                    "name": item.name,
                    "sourceType": item.source_type,
                    "revision": revision,
                }
                for item in self.credentials.values()
            ],
            "bindings": [
                {
                    "name": self.binding_name,
                    "revision": revision,
                    "match": {
                        "hosts": [self.binding_host],
                        "schemes": ["https"],
                        "methods": ["POST"],
                        "paths": ["/v1/*"],
                    },
                    "auth": {"type": "apiKey", "name": "x-api-key"},
                }
            ]
            if self.credentials
            else [],
        }


def assert_public_read(body: dict, secret: str) -> None:
    """A client should treat every public vault body as metadata."""
    blob = json.dumps(body, ensure_ascii=False)
    if secret and secret in blob:
        raise SystemExit("public body contains the credential value")
    if FAKE_GUEST_KEY != secret and secret == "":
        raise SystemExit("empty secret is not a useful check")

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in FORBIDDEN_KEYS:
                    raise SystemExit(f"public body has forbidden key {key}")
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)


def sanitize_validation_error(errors: list[dict]) -> dict:
    """Same key drop as the server's RequestValidationError handler."""
    sanitized = [
        {key: value for key, value in error.items() if key not in ("input", "ctx")}
        for error in errors
    ]
    return {"detail": sanitized}


def create(vault: EgressVault, name: str, value: str) -> tuple[int, dict]:
    if vault.sealed:
        return 409, {}
    if vault.revision != 0:
        return 409, {}
    vault.credentials[name] = StoredCredential(name, "inline", value)
    vault.revision = 1
    body = vault.public_state()
    assert_public_read(body, value)
    return 201, body


def patch_replace(
    vault: EgressVault, name: str, value: str, expected_revision: int
) -> tuple[int, dict]:
    if vault.sealed:
        return 409, {}
    if expected_revision != vault.revision:
        return 412, {}
    if name not in vault.credentials:
        return 400, {}
    # Order documented on the mutation model: delete, then replace, then add.
    vault.credentials[name] = StoredCredential(name, "inline", value)
    vault.revision += 1
    body = vault.public_state()
    assert_public_read(body, value)
    return 200, body


def main() -> None:
    vault = EgressVault()
    guest_env = {"ANTHROPIC_API_KEY": FAKE_GUEST_KEY}
    status, created = create(vault, "example-api-key", SECRET)
    print(f"POST /v1/sandboxes/fsb-demo/credential-vault -> {status}")
    print(json.dumps(created, ensure_ascii=False, indent=2))
    print(f"guest_env_holds_secret={SECRET in json.dumps(guest_env)}")

    status, patched = patch_replace(
        vault, "example-api-key", SECRET + "-rotated", expected_revision=1
    )
    print(f"PATCH expectedRevision=1 -> {status}")
    print(json.dumps(patched, ensure_ascii=False, indent=2))

    status, _ = patch_replace(
        vault, "example-api-key", SECRET + "-stale", expected_revision=1
    )
    print(
        f"PATCH stale expectedRevision=1 -> {status} "
        f"revision_unchanged={vault.revision == 2}"
    )

    vault.sealed = True
    status, _ = patch_replace(
        vault, "example-api-key", SECRET + "-while-paused", expected_revision=2
    )
    print(f"PATCH while sealed -> {status} revision_unchanged={vault.revision == 2}")

    leaked = {
        "type": "value_error",
        "loc": ["body", "credentials", 0, "source", "value"],
        "msg": "Input should be a valid string",
        "input": {"value": SECRET},
        "ctx": {"secret": SECRET},
    }
    print("422 detail after dropping input and ctx:")
    print(json.dumps(sanitize_validation_error([leaked]), ensure_ascii=False, indent=2))
    assert_public_read(sanitize_validation_error([leaked]), SECRET)


if __name__ == "__main__":
    main()
