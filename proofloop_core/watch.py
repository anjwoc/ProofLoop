from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, TextIO

from .events import validate_event
from .renderers import build_renderer


_LEVELS = {"debug": 0, "info": 1, "warning": 2, "error": 3}


def resolve_run_dir(
    *,
    repo: str | Path = ".",
    run: str | None = None,
    run_dir: str | Path | None = None,
) -> Path:
    if run_dir is not None:
        resolved = Path(run_dir).expanduser().resolve()
    else:
        if not run:
            raise ValueError("either run or run_dir is required")
        runs_dir = Path(repo).resolve() / ".proofloop" / "runs"
        if run == "latest":
            candidates = sorted(path for path in runs_dir.iterdir() if path.is_dir()) if runs_dir.exists() else []
            if not candidates:
                raise ValueError(f"no ProofLoop runs found under {runs_dir}")
            resolved = candidates[-1].resolve()
        else:
            resolved = (runs_dir / run).resolve()
    if not resolved.is_dir():
        raise ValueError(f"ProofLoop run directory does not exist: {resolved}")
    return resolved


def watch_events(
    run_dir: str | Path,
    *,
    stream: TextIO,
    output_format: str = "human",
    verbosity: str = "info",
    color: str = "auto",
    task_id: str | None = None,
    minimum_level: str | None = None,
    follow: bool = True,
    poll_interval: float = 0.1,
) -> int:
    if output_format not in {"human", "jsonl"}:
        raise ValueError("watch output format must be human or jsonl")
    if minimum_level is not None and minimum_level not in _LEVELS:
        raise ValueError(f"unsupported minimum level: {minimum_level}")
    if poll_interval <= 0:
        raise ValueError("poll_interval must be positive")
    source = Path(run_dir).resolve() / "events.jsonl"
    if not source.is_file():
        raise ValueError(f"event stream does not exist: {source}")
    renderer = build_renderer(output_format, stream, verbosity, color)
    rendered = 0
    buffer = ""
    line_number = 0

    with source.open("r", encoding="utf-8") as handle:
        while True:
            chunk = handle.read(8192)
            if chunk:
                buffer += chunk
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line_number += 1
                    if not line:
                        continue
                    event = _parse_event(line, line_number)
                    if not _matches(event, task_id=task_id, minimum_level=minimum_level):
                        continue
                    renderer.render(event)
                    rendered += 1
                continue
            if not follow:
                break
            time.sleep(poll_interval)
    return rendered


def _parse_event(line: str, line_number: int) -> dict[str, Any]:
    try:
        event = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid event JSON at line {line_number}: {exc.msg}") from exc
    try:
        return validate_event(event)
    except ValueError as exc:
        raise ValueError(f"invalid event schema at line {line_number}: {exc}") from exc


def _matches(
    event: dict[str, Any],
    *,
    task_id: str | None,
    minimum_level: str | None,
) -> bool:
    if task_id is not None and event.get("taskId") != task_id:
        return False
    if minimum_level is not None:
        event_level = str(event.get("level") or "info")
        if event_level not in _LEVELS or _LEVELS[event_level] < _LEVELS[minimum_level]:
            return False
    return True
