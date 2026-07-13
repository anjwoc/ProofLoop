from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .renderers import build_renderer


class EventStoreCorruptError(RuntimeError):
    pass


_LEVELS = {"debug", "info", "warning", "error"}
_EVENT_ID = re.compile(r"^evt-[0-9]{6,}$")


def validate_event(event: Any, *, expected_run_id: str | None = None) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    required_strings = ("eventId", "runId", "timestamp", "type", "phase", "message")
    if event.get("schemaVersion") != "1":
        raise ValueError("schemaVersion must be '1'")
    if any(not isinstance(event.get(key), str) or not event[key] for key in required_strings):
        raise ValueError("required string field is missing")
    if not _EVENT_ID.fullmatch(event["eventId"]):
        raise ValueError("invalid eventId")
    if expected_run_id is not None and event["runId"] != expected_run_id:
        raise ValueError("runId mismatch")
    sequence = event.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("sequence must be a positive integer")
    if event["eventId"] != f"evt-{sequence:06d}":
        raise ValueError("eventId does not match sequence")
    if event.get("level") not in _LEVELS:
        raise ValueError("invalid event level")
    if not isinstance(event.get("data"), dict):
        raise ValueError("data must be an object")
    if "taskId" in event and (not isinstance(event["taskId"], str) or not event["taskId"]):
        raise ValueError("taskId must be a non-empty string")
    try:
        timestamp = datetime.fromisoformat(event["timestamp"])
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return event


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
            try:
                validate_event(event, expected_run_id=self.run_id)
            except ValueError as exc:
                raise EventStoreCorruptError(f"invalid event schema at line {line_number}: {exc}") from exc
            sequence = event["sequence"]
            if sequence <= last_sequence:
                raise EventStoreCorruptError(f"non-monotonic sequence at line {line_number}")
            last_sequence = sequence
        return last_sequence
