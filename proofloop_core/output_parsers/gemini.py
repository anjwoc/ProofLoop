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


class GeminiOutputParser(StructuredOutputParser):
    def model_from_event(self, value: dict[str, Any]) -> str | None:
        if value.get("type") not in {"init", "session.started", "model_resolved"}:
            return None
        return explicit_model(value, ("model", "model_id", "modelId", "resolved_model", "resolvedModel"))

    def session_events_from_event(self, value: dict[str, Any]) -> list[NormalizedHostEvent]:
        event_type = value.get("type")
        if event_type in {"init", "session.started"}:
            session_id = value.get("session_id") or value.get("sessionId")
            if isinstance(session_id, str) and session_id:
                return [session_started_event(session_id, value)]
        if event_type == "message" and value.get("role") in {"assistant", "model"}:
            text = value.get("content") or value.get("text")
            if isinstance(text, str) and text:
                return [session_event("agent_message_chunk", value, text=text)]
        if event_type in {"tool_use", "tool_call"}:
            return [session_event("tool_call_started", value, text=str(value.get("tool_name") or value.get("name") or "tool"))]
        if event_type in {"tool_result", "tool_call_result"}:
            return [session_event("tool_call_updated", value, text=str(value.get("tool_name") or value.get("name") or "tool"))]
        if event_type == "result":
            events = [session_event("session_result", value, text=str(value.get("status") or "result"))]
            candidate = value.get("usage") or value.get("usageMetadata") or value.get("stats") or value.get("tokens")
            normalized = usage_event(
                candidate,
                session_id=str(value.get("session_id") or value.get("sessionId") or "") or None,
                source_event_id=str(value.get("id") or "result"),
                cache_read_is_subset=True,
            ) if isinstance(candidate, dict) else None
            if normalized:
                events.append(normalized)
            return events
        return []
