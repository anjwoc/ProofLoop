from __future__ import annotations

import json
from typing import Any, TextIO


class JsonlRenderer:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream

    def render(self, event: dict[str, Any]) -> None:
        serialized = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        self.stream.write(serialized + "\n")
        self.stream.flush()
