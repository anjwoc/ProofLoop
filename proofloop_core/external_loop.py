from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .checks import run_checks
from .diff_guard import inspect_diff
from .events import EventEmitter
from .fingerprint import fingerprint_check_report
from .io import write_json
from .repair import decide_next
from .task_brief import load_task_brief
from .process_runner import ProcessRunner


_MAX_LIVE_OUTPUT_EVENT_CHARS = 8_000


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def _invoke(
    command: list[str],
    repo: Path,
    env: dict[str, str],
    timeout: int,
    call_dir: Path,
    role: str,
    sequence: int,
    emitter: EventEmitter | None,
) -> dict[str, Any]:
    def on_line(stream: str, line: str) -> None:
        if emitter is not None and line.strip():
            visible = line.rstrip("\r\n")
            emitter.emit(
                "role.output",
                phase="EXECUTE",
                message=f"{role} produced {stream} output.",
                data={
                    "role": role,
                    "attempt": sequence,
                    "stream": stream,
                    "text": visible[:_MAX_LIVE_OUTPUT_EVENT_CHARS],
                    "truncated": len(visible) > _MAX_LIVE_OUTPUT_EVENT_CHARS,
                },
            )

    def on_heartbeat(process_id: int, elapsed: float) -> None:
        if emitter is not None:
            emitter.emit(
                "role.progress",
                phase="EXECUTE",
                message=f"{role} is still running.",
                data={"role": role, "attempt": sequence, "processId": process_id, "elapsedSeconds": elapsed},
            )

    completed = ProcessRunner().run(
        command,
        cwd=repo,
        env={**os.environ, **env},
        stdout_path=call_dir / "stdout.log",
        stderr_path=call_dir / "stderr.log",
        timeout_seconds=timeout,
        on_line=on_line,
        on_heartbeat=on_heartbeat if emitter is not None else None,
    )
    return {
        "command": command,
        "exitCode": completed.exit_code,
        "timedOut": completed.timed_out,
        "cancelled": completed.cancelled,
        "durationSeconds": completed.duration_seconds,
        "stdoutRef": completed.stdout_ref,
        "stderrRef": completed.stderr_ref,
    }


def run_external_loop(
    task_path: str | Path,
    repository: str | Path,
    run_dir: str | Path,
    fast_command: list[str],
    recovery_command: list[str] | None,
    baseline: str = "HEAD",
    timeout_seconds: int = 900,
    *,
    emitter: EventEmitter | None = None,
) -> dict[str, Any]:
    task = load_task_brief(task_path)
    repo = Path(repository).resolve()
    root = Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    attempts_path = root / "attempts.jsonl"
    attempts: list[dict[str, Any]] = []
    role = "implementer_fast"
    sequence = 0

    while True:
        sequence += 1
        command = fast_command if role == "implementer_fast" else recovery_command
        if not command:
            final = {"verdict": "BLOCKED", "reason": f"no command configured for {role}", "attempts": attempts}
            write_json(root / "loop-result.json", final)
            return final
        call_dir = root / "invocations" / f"{sequence:02d}-{role}"
        call_dir.mkdir(parents=True, exist_ok=True)
        invocation = _invoke(
            command,
            repo,
            {
                "PROOFLOOP_TASK_PATH": str(Path(task_path).resolve()),
                "PROOFLOOP_RUN_DIR": str(root),
                "PROOFLOOP_ATTEMPT": str(sequence),
                "PROOFLOOP_ROLE": role,
            },
            timeout_seconds,
            call_dir,
            role,
            sequence,
            emitter,
        )

        checks = run_checks(
            task,
            repo,
            root / "checks" / f"attempt-{sequence:02d}",
            emitter=emitter,
        )
        diff = inspect_diff(task, repo, baseline)
        fingerprint = fingerprint_check_report(checks)
        attempt = {
            "sequence": sequence,
            "role": role,
            "invocation": invocation,
            "checkVerdict": checks["verdict"],
            "diffVerdict": diff["verdict"],
            "failureFingerprint": fingerprint,
            "classification": "IMPLEMENTATION_FAILURE" if checks["verdict"] == "FAIL" else None,
        }
        attempts.append(attempt)
        _append_jsonl(attempts_path, attempt)
        write_json(root / "diff-guard.json", diff)
        write_json(root / "checks" / "checks.json", checks)

        decision = decide_next(attempts, task.max_fast_attempts, task.max_recovery_attempts)
        _append_jsonl(root / "decisions.jsonl", {"sequence": sequence, **decision})
        action = decision["action"]
        if action == "REVIEW":
            final = {"verdict": "READY_FOR_REVIEW", "reason": decision["reason"], "attempts": attempts}
            write_json(root / "loop-result.json", final)
            return final
        if action in {"RETRY_FAST", "RUN_FAST"}:
            role = "implementer_fast"
            continue
        if action in {"RUN_RECOVERY", "RETRY_RECOVERY"}:
            role = "implementer_recovery"
            continue
        final = {"verdict": action, "reason": decision["reason"], "attempts": attempts}
        write_json(root / "loop-result.json", final)
        return final
