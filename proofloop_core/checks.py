from __future__ import annotations

import os
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .io import sha256_file, write_json
from .task_brief import TaskBrief


def _safe_name(index: int, name: str | None) -> str:
    raw = name or f"check-{index:02d}"
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw).strip("-") or f"check-{index:02d}"


def run_checks(task: TaskBrief, repository: str | Path, output_dir: str | Path) -> dict[str, Any]:
    repo = Path(repository).resolve()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for index, check in enumerate(task.required_checks, start=1):
        name = _safe_name(index, check.name)
        stdout_path = output / f"{index:02d}-{name}.stdout.log"
        stderr_path = output / f"{index:02d}-{name}.stderr.log"
        cwd = (repo / check.cwd).resolve() if check.cwd else repo
        if repo not in cwd.parents and cwd != repo:
            raise ValueError(f"check cwd escapes repository: {cwd}")
        started = time.time()
        timed_out = False
        try:
            completed = subprocess.run(
                check.command,
                cwd=cwd,
                env={**os.environ, "PROOFLOOP_TASK_ID": task.task_id},
                capture_output=True,
                text=True,
                timeout=check.timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            timed_out = True
            exit_code = 124
            stdout = error.stdout or ""
            stderr = error.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            stderr += f"\nProofLoop timeout after {check.timeout_seconds}s\n"
        finished = time.time()
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        results.append(
            {
                "name": check.name or name,
                "command": check.command,
                "cwd": str(cwd),
                "exitCode": exit_code,
                "timedOut": timed_out,
                "startedAtEpoch": started,
                "finishedAtEpoch": finished,
                "durationSeconds": round(finished - started, 6),
                "stdoutRef": str(stdout_path),
                "stderrRef": str(stderr_path),
                "stdoutSha256": sha256_file(stdout_path),
                "stderrSha256": sha256_file(stderr_path),
                "status": "PASS" if exit_code == 0 else "FAIL",
            }
        )

    verdict = "PASS" if all(item["exitCode"] == 0 for item in results) else "FAIL"
    report = {
        "schemaVersion": "1.0",
        "taskId": task.task_id,
        "repository": str(repo),
        "verdict": verdict,
        "checks": results,
    }
    write_json(output / "checks.json", report)
    return report
