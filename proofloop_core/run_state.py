from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from .io import read_json, write_json


def _prune_old_records(repo: Path, keep: int = 30) -> None:
    proofloop_dir = repo / ".proofloop"
    if not proofloop_dir.exists():
        return
    for subdir_name in ("runs", "relay", "requests"):
        target_dir = proofloop_dir / subdir_name
        if not target_dir.exists():
            continue
        try:
            items = sorted(target_dir.iterdir(), key=lambda p: (p.stat().st_mtime, p.name))
        except OSError:
            continue
        if len(items) > keep:
            for item in items[:-keep]:
                try:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                except OSError:
                    continue


def start_run(repository: str | Path, request: str = "") -> dict[str, Any]:
    repo = Path(repository).resolve()
    _prune_old_records(repo, keep=30)
    run_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = repo / ".proofloop" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    state = {
        "schemaVersion": "1.0",
        "runId": run_id,
        "runDir": str(run_dir),
        "repository": str(repo),
        "request": request,
        "status": "ACTIVE",
        "createdAtEpoch": time.time(),
    }
    write_json(run_dir / "run.json", state)
    write_json(repo / ".proofloop" / "active-run.json", state)
    return state


def load_active_run(repository: str | Path) -> dict[str, Any] | None:
    path = Path(repository).resolve() / ".proofloop" / "active-run.json"
    return read_json(path) if path.exists() else None


def finalize_run(repository: str | Path, truth_report: dict[str, Any]) -> None:
    repo = Path(repository).resolve()
    active_path = repo / ".proofloop" / "active-run.json"
    if not active_path.exists():
        return
    state = read_json(active_path)
    state["status"] = "FINALIZED"
    state["finalVerdict"] = truth_report.get("verdict")
    state["finalizedAtEpoch"] = time.time()
    write_json(Path(state["runDir"]) / "run.json", state)
    active_path.unlink(missing_ok=True)


def abort_run(repository: str | Path, reason: str) -> dict[str, Any]:
    repo = Path(repository).resolve()
    active = load_active_run(repo)
    if not active:
        return {"status": "NO_ACTIVE_RUN"}
    report = {"schemaVersion": "1.0", "verdict": "BLOCKED", "reason": reason}
    write_json(Path(active["runDir"]) / "truth-report.json", report)
    finalize_run(repo, report)
    return report
