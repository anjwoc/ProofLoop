from __future__ import annotations

from typing import Any

from .base import StructuredOutputParser, explicit_model


class AntigravityOutputParser(StructuredOutputParser):
    def model_from_event(self, value: dict[str, Any]) -> str | None:
        marker = value.get("event") or value.get("type")
        if marker not in {"model_resolved", "model.resolved"}:
            return None
        return explicit_model(value, ("resolvedModel", "resolved_model", "modelId", "model_id", "model"))
