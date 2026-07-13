from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .fingerprint import fingerprint_check_report
from .io import read_json, write_json
from .repair import decide_next
from .task_brief import load_task_brief


def record_attempt(task_path: str | Path, run_dir: str | Path, role: str, observed_model: str | None = None) -> dict[str, Any]:
    task = load_task_brief(task_path)
    root = Path(run_dir)
    checks = read_json(root / "checks" / "checks.json")
    diff = read_json(root / "diff-guard.json")
    attempts_path = root / "attempts.jsonl"
    attempts: list[dict[str, Any]] = []
    if attempts_path.exists():
        attempts = [json.loads(line) for line in attempts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    attempt = {
        "sequence": len(attempts) + 1,
        "timestampEpoch": time.time(),
        "role": role,
        "observedModel": observed_model,
        "checkVerdict": checks.get("verdict"),
        "diffVerdict": diff.get("verdict"),
        "failureFingerprint": fingerprint_check_report(checks),
        "classification": None,
        "checksRef": str(root / "checks" / "checks.json"),
        "diffGuardRef": str(root / "diff-guard.json"),
    }
    attempts.append(attempt)
    with attempts_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(attempt, ensure_ascii=False) + "\n")
    decision = decide_next(attempts, task.max_fast_attempts, task.max_recovery_attempts)
    write_json(root / "next-action.json", decision)
    return {"attempt": attempt, "decision": decision}
