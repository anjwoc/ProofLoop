from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from .redact import redact_secrets


@dataclass(frozen=True)
class RelayPoll:
    """The newly observed portion of a parent-owned ProofLoop relay.

    A host conversation cannot receive an unsolicited subprocess callback.  It
    must make short, normal terminal calls while the detached parent runs.  A
    durable cursor lets every one of those calls print precisely the unseen
    observable event lines, without replaying the entire run or reading a
    provider's private transcript.
    """

    lines: tuple[str, ...]
    active: bool
    pid: int | None


def poll_relay(relay_dir: str | Path) -> RelayPoll:
    root = Path(relay_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"relay directory does not exist: {root}")
    output = root / "output.log"
    cursor = root / "next-line"
    try:
        next_line = max(1, int(cursor.read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        next_line = 1

    if output.is_file():
        raw_lines = output.read_text(encoding="utf-8", errors="replace").splitlines()
    else:
        raw_lines = []
    lines = tuple(redact_secrets(line) for line in raw_lines[next_line - 1 :])
    cursor.write_text(f"{len(raw_lines) + 1}\n", encoding="utf-8")

    pid = _read_pid(root / "pid")
    return RelayPoll(lines=lines, active=_is_alive(pid), pid=pid)


def wait_and_poll_relay(relay_dir: str | Path, *, wait_seconds: float = 3.0) -> RelayPoll:
    if not 0 <= wait_seconds <= 10:
        raise ValueError("wait_seconds must be between 0 and 10")
    if wait_seconds:
        time.sleep(wait_seconds)
    return poll_relay(relay_dir)


def _read_pid(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return value if value > 0 else None


def _is_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
