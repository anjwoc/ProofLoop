"""Immutable raw-request envelope (V2 architecture section 5.1).

The envelope is the authoritative, never-rewritten record of exactly what the
user asked for. It preserves the raw text byte-for-byte (no stripping) and a
SHA-256 over those exact bytes, so every downstream artifact can reference an
unforgeable request identity. Later refinement may reinterpret the request but
must never mutate this record or widen the authority it captures.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class RequestEnvelope:
    request_id: str
    raw_text: str
    raw_hash: str
    received_at: str
    repo_root: str
    host_requested: str | None
    explicit_permissions: tuple[str, ...]
    explicit_denials: tuple[str, ...]
    user_constraints: tuple[str, ...]
    invocation_source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "requestId": self.request_id,
            "rawText": self.raw_text,
            "rawHash": self.raw_hash,
            "receivedAt": self.received_at,
            "repoRoot": self.repo_root,
            "hostRequested": self.host_requested,
            "explicitPermissions": list(self.explicit_permissions),
            "explicitDenials": list(self.explicit_denials),
            "userConstraints": list(self.user_constraints),
            "invocationSource": self.invocation_source,
        }


def hash_raw_text(raw_text: str) -> str:
    """Return the canonical ``sha256:<hex>`` digest of the exact request bytes."""
    return "sha256:" + hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def create(
    *,
    request_id: str,
    raw_text: str,
    repo_root: str,
    invocation_source: str,
    host_requested: str | None = None,
    received_at: str | None = None,
    explicit_permissions: tuple[str, ...] | list[str] = (),
    explicit_denials: tuple[str, ...] | list[str] = (),
    user_constraints: tuple[str, ...] | list[str] = (),
) -> RequestEnvelope:
    if not raw_text or not raw_text.strip():
        raise ValueError("raw_text must be a non-empty request")
    return RequestEnvelope(
        request_id=request_id,
        raw_text=raw_text,
        raw_hash=hash_raw_text(raw_text),
        received_at=received_at or datetime.now(timezone.utc).isoformat(),
        repo_root=str(repo_root),
        host_requested=host_requested,
        explicit_permissions=tuple(explicit_permissions),
        explicit_denials=tuple(explicit_denials),
        user_constraints=tuple(user_constraints),
        invocation_source=invocation_source,
    )
