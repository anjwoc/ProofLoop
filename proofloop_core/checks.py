from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from .events import EventEmitter
from .io import sha256_file, write_json
from .process_runner import ProcessRunner
from .task_brief import TaskBrief


def _safe_name(index: int, name: str | None) -> str:
    raw = name or f"check-{index:02d}"
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw).strip("-") or f"check-{index:02d}"


def _failure_evidence(stdout_path: Path, stderr_path: Path) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    for path in (stdout_path, stderr_path):
        lines.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        )
    failed = [
        line
        for line in lines
        if re.search(r"(?:^|\s)(?:FAIL|FAILED|ERROR)(?:\s|:|$)", line, re.IGNORECASE)
    ]
    return failed[-20:], lines[-20:]


def run_checks(
    task: TaskBrief,
    repository: str | Path,
    output_dir: str | Path,
    *,
    emitter: EventEmitter | None = None,
    phase: str = "VERIFY",
) -> dict[str, Any]:
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
        command_id = f"check-{index:03d}"
        if emitter is not None:
            emitter.emit(
                "check.started",
                phase=phase,
                message=f"Check {check.name or name} started.",
                task_id=task.task_id,
                data={
                    "commandId": command_id,
                    "name": check.name or name,
                    "command": check.command,
                    "cwd": str(cwd),
                },
            )
        started = time.time()

        def on_line(stream_name: str, line: str) -> None:
            if emitter is None:
                return
            emitter.emit(
                "check.output",
                phase=phase,
                message=f"Check {check.name or name} produced {stream_name} output.",
                level="debug",
                task_id=task.task_id,
                data={
                    "commandId": command_id,
                    "stream": stream_name,
                    "text": line,
                },
            )

        process_result = ProcessRunner().run(
            check.command,
            cwd=cwd,
            env={**os.environ, "PROOFLOOP_TASK_ID": task.task_id},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_seconds=check.timeout_seconds,
            on_line=on_line,
        )
        if process_result.timed_out:
            with stderr_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\nProofLoop timeout after {check.timeout_seconds}s\n")
                handle.flush()
        finished = time.time()
        result = {
            "name": check.name or name,
            "command": check.command,
            "cwd": str(cwd),
            "exitCode": process_result.exit_code,
            "timedOut": process_result.timed_out,
            "startedAtEpoch": started,
            "finishedAtEpoch": finished,
            "durationSeconds": round(finished - started, 6),
            "stdoutRef": str(stdout_path),
            "stderrRef": str(stderr_path),
            "stdoutSha256": sha256_file(stdout_path),
            "stderrSha256": sha256_file(stderr_path),
            "status": "PASS" if process_result.exit_code == 0 else "FAIL",
        }
        results.append(result)
        if emitter is not None:
            event_type = "check.completed" if process_result.exit_code == 0 else "check.failed"
            failed_tests, output_tail = (
                ([], [])
                if process_result.exit_code == 0
                else _failure_evidence(stdout_path, stderr_path)
            )
            failure_reason = None
            if process_result.timed_out:
                failure_reason = f"timeout after {check.timeout_seconds}s"
            elif process_result.cancelled:
                failure_reason = "check cancelled"
            elif process_result.exit_code != 0:
                failure_reason = f"command exited with {process_result.exit_code}"
            emitter.emit(
                event_type,
                phase=phase,
                message=f"Check {check.name or name} {result['status'].lower()}.",
                level="info" if process_result.exit_code == 0 else "error",
                task_id=task.task_id,
                data={
                    "commandId": command_id,
                    "name": check.name or name,
                    "command": check.command,
                    "cwd": str(cwd),
                    "exitCode": process_result.exit_code,
                    "timedOut": process_result.timed_out,
                    "durationSeconds": result["durationSeconds"],
                    "stdoutRef": str(stdout_path),
                    "stderrRef": str(stderr_path),
                    "failedTests": failed_tests,
                    "outputTail": output_tail,
                    "failureReason": failure_reason,
                },
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
