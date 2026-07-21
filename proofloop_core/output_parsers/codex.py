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


class CodexOutputParser(StructuredOutputParser):
    def model_from_event(self, value: dict[str, Any]) -> str | None:
        if value.get("type") not in {"thread.started", "session.started", "turn.started"}:
            return None
        return explicit_model(value, ("model", "model_id", "modelId", "resolved_model", "resolvedModel"))

    def session_events_from_event(self, value: dict[str, Any]) -> list[NormalizedHostEvent]:
        event_type = value.get("type")
        raw_item = value.get("item")
        item: dict[str, Any] = raw_item if isinstance(raw_item, dict) else {}
        item_type = item.get("type")
        if event_type in {"thread.started", "session.started"}:
            session_id = value.get("thread_id") or value.get("threadId") or value.get("session_id") or value.get("sessionId")
            if isinstance(session_id, str) and session_id:
                return [session_started_event(session_id, value)]
        if event_type == "turn.completed":
            usage = value.get("usage")
            event = usage_event(
                usage,
                session_id=str(value.get("thread_id") or value.get("threadId") or "") or None,
                source_event_id=str(value.get("turn_id") or value.get("turnId") or event_type),
                cache_read_is_subset=True,
            ) if isinstance(usage, dict) else None
            return [event] if event else []
        raw_payload = value.get("payload")
        payload: dict[str, Any] = raw_payload if isinstance(raw_payload, dict) else {}
        if event_type == "event_msg" and payload.get("type") == "token_count":
            raw_info = payload.get("info")
            info: dict[str, Any] = raw_info if isinstance(raw_info, dict) else {}
            usage = info.get("last_token_usage")
            event = usage_event(
                usage,
                measurement_kind="cumulative",
                cache_read_is_subset=True,
            ) if isinstance(usage, dict) else None
            return [event] if event else []
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
