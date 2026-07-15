from __future__ import annotations

from typing import Any

from .base import (
    NormalizedHostEvent,
    StructuredOutputParser,
    explicit_model,
    session_event,
    session_started_event,
    usage_event,
)


class AntigravityOutputParser(StructuredOutputParser):
    def model_from_event(self, value: dict[str, Any]) -> str | None:
        marker = value.get("event") or value.get("type")
        if marker not in {"model_resolved", "model.resolved"}:
            return None
        return explicit_model(value, ("resolvedModel", "resolved_model", "modelId", "model_id", "model"))

    def session_events_from_event(self, value: dict[str, Any]) -> list[NormalizedHostEvent]:
        marker = value.get("event") or value.get("type")
        if marker in {"session_started", "session.started"}:
            session_id = value.get("sessionId") or value.get("session_id")
            if isinstance(session_id, str) and session_id:
                return [session_started_event(session_id, value)]
        if marker in {"agent_message", "message"}:
            text = value.get("text") or value.get("message")
            if isinstance(text, str) and text:
                return [session_event("agent_message_chunk", value, text=text)]
        if marker in {"tool_call", "tool.started"}:
            return [session_event("tool_call_started", value, text=str(value.get("name") or "tool"))]
        if marker in {"tool_result", "tool.completed"}:
            return [session_event("tool_call_updated", value, text=str(value.get("name") or "tool"))]
        if marker in {"result", "session.completed", "usage", "usage_update"}:
            candidate = value.get("usage") or value.get("tokens") or value
            normalized = usage_event(
                candidate,
                measurement_kind="cumulative" if marker == "usage_update" else "final",
                session_id=str(value.get("sessionId") or value.get("session_id") or "") or None,
                source_event_id=str(value.get("id") or marker),
            ) if isinstance(candidate, dict) else None
            return [normalized] if normalized else []
        return []
