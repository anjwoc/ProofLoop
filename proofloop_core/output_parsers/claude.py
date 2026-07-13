from __future__ import annotations

from typing import Any

from .base import StructuredOutputParser, explicit_model


class ClaudeOutputParser(StructuredOutputParser):
    def model_from_event(self, value: dict[str, Any]) -> str | None:
        if value.get("type") != "system" or value.get("subtype") != "init":
            return None
        return explicit_model(value, ("model", "model_id", "modelId", "resolved_model", "resolvedModel"))
