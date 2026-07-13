from __future__ import annotations

from typing import Any


class QuietRenderer:
    def render(self, event: dict[str, Any]) -> None:
        del event
