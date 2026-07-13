from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .renderers import build_renderer


class EventStoreCorruptError(RuntimeError):
    pass


class EventEmitter:
    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        stream: TextIO,
        output_format: str,
        verbosity: str = "info",
        color: str = "auto",
    ) -> None:
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "events.jsonl"
        self.renderer = build_renderer(output_format, stream, verbosity, color)
        self._lock = threading.RLock()
        self._render_enabled = True
        self._sequence = self._recover_sequence()

    def emit(
        self,
        event_type: str,
        *,
        phase: str,
        message: str,
        level: str = "info",
        task_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if level not in {"debug", "info", "warning", "error"}:
            raise ValueError(f"unsupported event level: {level}")
        with self._lock:
            self._sequence += 1
            event: dict[str, Any] = {
                "schemaVersion": "1",
                "eventId": f"evt-{self._sequence:06d}",
                "runId": self.run_id,
                "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "sequence": self._sequence,
                "type": event_type,
                "level": level,
                "phase": phase,
                "message": message,
                "data": dict(data or {}),
            }
            if task_id is not None:
                event["taskId"] = task_id
            serialized = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")
                handle.flush()
            if self._render_enabled:
                try:
                    self.renderer.render(event)
                except BrokenPipeError:
                    self._render_enabled = False
            return event

    def _recover_sequence(self) -> int:
        if not self.path.exists():
            return 0
        text = self.path.read_text(encoding="utf-8")
        if not text:
            return 0
        if not text.endswith("\n"):
            last_newline = text.rfind("\n")
            tail = text[last_newline + 1 :]
            try:
                json.loads(tail)
            except json.JSONDecodeError:
                corrupt = self.run_dir / "events.corrupt-tail.log"
                if corrupt.exists() and corrupt.stat().st_size:
                    with corrupt.open("a", encoding="utf-8") as handle:
                        handle.write("\n" + tail)
                else:
                    corrupt.write_text(tail, encoding="utf-8")
                text = text[: last_newline + 1]
                self.path.write_text(text, encoding="utf-8")
            else:
                text += "\n"
                self.path.write_text(text, encoding="utf-8")

        last_sequence = 0
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EventStoreCorruptError(f"invalid event JSON at line {line_number}: {exc.msg}") from exc
            if not isinstance(event, dict) or not isinstance(event.get("sequence"), int):
                raise EventStoreCorruptError(f"invalid event schema at line {line_number}")
            if event.get("runId") != self.run_id:
                raise EventStoreCorruptError(f"runId mismatch at line {line_number}")
            sequence = event["sequence"]
            if sequence <= last_sequence:
                raise EventStoreCorruptError(f"non-monotonic sequence at line {line_number}")
            last_sequence = sequence
        return last_sequence
