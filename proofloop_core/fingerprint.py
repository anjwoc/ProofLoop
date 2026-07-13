from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_VOLATILE = [
    re.compile(r"0x[0-9a-fA-F]+"),
    re.compile(r"\b\d+(?:\.\d+)?s\b"),
    re.compile(r"/tmp/[^\s:]+"),
    re.compile(r"\\tmp\\[^\s:]+"),
    re.compile(r"\bline \d+\b", re.IGNORECASE),
]


def normalize_failure_text(text: str) -> str:
    normalized = text
    for pattern in _VOLATILE:
        normalized = pattern.sub("<volatile>", normalized)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    return "\n".join(lines[:80])


def fingerprint_check_report(report: dict[str, Any]) -> str | None:
    failed = [item for item in report.get("checks", []) if item.get("status") != "PASS"]
    if not failed:
        return None
    payload: list[dict[str, Any]] = []
    for item in failed:
        stderr_ref = item.get("stderrRef")
        stdout_ref = item.get("stdoutRef")
        text = ""
        for ref in (stderr_ref, stdout_ref):
            if isinstance(ref, str) and Path(ref).exists():
                text += "\n" + Path(ref).read_text(encoding="utf-8", errors="replace")
        payload.append(
            {
                "name": item.get("name"),
                "command": item.get("command"),
                "exitCode": item.get("exitCode"),
                "output": normalize_failure_text(text),
            }
        )
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]
