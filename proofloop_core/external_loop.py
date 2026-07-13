from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .checks import run_checks
from .diff_guard import inspect_diff
from .fingerprint import fingerprint_check_report
from .io import write_json
from .repair import decide_next
from .task_brief import load_task_brief


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def _invoke(command: list[str], repo: Path, env: dict[str, str], timeout: int) -> dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=repo,
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
        timed_out = False
    except subprocess.TimeoutExpired as error:
        exit_code = 124
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        timed_out = True
    return {
        "command": command,
        "exitCode": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "timedOut": timed_out,
        "durationSeconds": round(time.time() - started, 6),
    }


def run_external_loop(
    task_path: str | Path,
    repository: str | Path,
    run_dir: str | Path,
    fast_command: list[str],
    recovery_command: list[str] | None,
    baseline: str = "HEAD",
    timeout_seconds: int = 900,
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
        )
        call_dir = root / "invocations" / f"{sequence:02d}-{role}"
        call_dir.mkdir(parents=True, exist_ok=True)
        (call_dir / "stdout.log").write_text(invocation.pop("stdout"), encoding="utf-8")
        (call_dir / "stderr.log").write_text(invocation.pop("stderr"), encoding="utf-8")
        invocation["stdoutRef"] = str(call_dir / "stdout.log")
        invocation["stderrRef"] = str(call_dir / "stderr.log")

        checks = run_checks(task, repo, root / "checks" / f"attempt-{sequence:02d}")
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
