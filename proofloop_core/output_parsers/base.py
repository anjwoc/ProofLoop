from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class NormalizedHostEvent:
    event_type: str
    message: str
    data: dict[str, Any]
    level: str = "info"


class HostOutputParser(Protocol):
    def feed(self, stream: str, line: str) -> list[NormalizedHostEvent]: ...


def explicit_model(value: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def normalize_known_error(value: dict[str, Any]) -> list[NormalizedHostEvent]:
    tokens = " ".join(
        str(value.get(key) or "").lower()
        for key in ("type", "event", "code", "error_code", "status", "subtype")
    )
    message = str(value.get("message") or value.get("error") or "Host capability degraded.")
    if "rate_limit" in tokens or "rate-limit" in tokens:
        return [
            NormalizedHostEvent(
                "capability.degraded",
                message,
                {"reasonCode": "RATE_LIMIT", "hostMessage": message},
                "warning",
            )
        ]
    if "permission" in tokens or "approval" in tokens:
        return [
            NormalizedHostEvent(
                "capability.degraded",
                message,
                {"reasonCode": "PERMISSION_REQUIRED", "hostMessage": message},
                "warning",
            )
        ]
    if any(token in tokens.split() for token in ("error", "failed", "failure", "fatal")):
        return [
            NormalizedHostEvent(
                "capability.degraded",
                message,
                {"reasonCode": "HOST_ERROR", "hostMessage": message},
                "error",
            )
        ]
    return []


class StructuredOutputParser:
    def model_from_event(self, value: dict[str, Any]) -> str | None:
        del value
        return None

    def feed(self, stream: str, line: str) -> list[NormalizedHostEvent]:
        del stream
        try:
            value = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(value, dict):
            return []
        events: list[NormalizedHostEvent] = []
        model = self.model_from_event(value)
        if model:
            events.append(
                NormalizedHostEvent(
                    "role.model_observed",
                    "Host model observed.",
                    {"observedModel": model, "evidenceLevel": "HOST_OUTPUT"},
                )
            )
        events.extend(normalize_known_error(value))
        return events
