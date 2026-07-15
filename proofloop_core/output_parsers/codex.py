from __future__ import annotations

from typing import Any

from .base import NormalizedHostEvent, StructuredOutputParser, explicit_model, session_event


class CodexOutputParser(StructuredOutputParser):
    def model_from_event(self, value: dict[str, Any]) -> str | None:
        if value.get("type") not in {"thread.started", "session.started", "turn.started"}:
            return None
        return explicit_model(value, ("model", "model_id", "modelId", "resolved_model", "resolvedModel"))

    def session_events_from_event(self, value: dict[str, Any]) -> list[NormalizedHostEvent]:
        event_type = value.get("type")
        item = value.get("item") if isinstance(value.get("item"), dict) else {}
        item_type = item.get("type")
        if event_type == "item.completed" and item_type in {"agent_message", "message"}:
            text = item.get("text") or item.get("content")
            if isinstance(text, str) and text:
                return [session_event("agent_message_chunk", item, text=text)]
        if event_type == "item.started" and item_type not in {None, "agent_message", "message"}:
            return [session_event("tool_call_started", item, text=str(item.get("name") or item_type))]
        if event_type in {"item.updated", "item.completed"} and item_type not in {None, "agent_message", "message"}:
            return [session_event("tool_call_updated", item, text=str(item.get("name") or item_type))]
        if event_type == "turn.started":
            return [session_event("plan_updated", value, text="Codex turn started")]
        return []
