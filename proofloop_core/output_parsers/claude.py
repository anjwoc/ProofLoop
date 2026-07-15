from __future__ import annotations

from typing import Any

from .base import NormalizedHostEvent, StructuredOutputParser, content_blocks, explicit_model, session_event


class ClaudeOutputParser(StructuredOutputParser):
    def model_from_event(self, value: dict[str, Any]) -> str | None:
        if value.get("type") != "system" or value.get("subtype") != "init":
            return None
        return explicit_model(value, ("model", "model_id", "modelId", "resolved_model", "resolvedModel"))

    def session_events_from_event(self, value: dict[str, Any]) -> list[NormalizedHostEvent]:
        event_type = value.get("type")
        events: list[NormalizedHostEvent] = []
        if event_type == "assistant":
            for block in content_blocks(value):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    events.append(session_event("agent_message_chunk", block, text=block["text"]))
                elif block.get("type") == "tool_use":
                    events.append(session_event("tool_call_started", block, text=str(block.get("name") or "tool")))
        elif event_type == "user":
            for block in content_blocks(value):
                if block.get("type") == "tool_result":
                    events.append(session_event("tool_call_updated", block, text="tool result"))
        elif event_type == "result":
            events.append(session_event("session_result", value, text=str(value.get("subtype") or "result")))
        return events
