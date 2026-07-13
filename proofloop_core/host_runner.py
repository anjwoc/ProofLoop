from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .hosts import capability, detect_model
from .trace import summarize_trace
from .io import write_json


def _append(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _default_prompt(role: str, task_path: str | None, run_dir: Path) -> str:
    role_text = {
        "planner_deep": "Create the smallest evidence-based implementation plan and task brief. Do not edit production code.",
        "implementer_fast": "Implement exactly one approved task with the smallest change. Use TDD and do not claim checks passed.",
        "implementer_recovery": "Fix the root cause using the exact failure evidence. Do not broaden the task contract.",
        "reviewer_deep": "Independently review the task, real diff, checks, test integrity, claims, and simplicity. Do not edit code.",
    }[role]
    task = f" Read the task brief at {task_path}." if task_path else ""
    return (
        f"Act as ProofLoop role {role}. {role_text}{task} "
        f"Use the evidence run at {run_dir}. Use $HOME/.proofloop/bin/proofloop-core for deterministic checks and truth reporting."
    )


def invoke_role(
    host: str,
    role: str,
    repository: str | Path,
    run_dir: str | Path,
    prompt: str | None = None,
    task_path: str | None = None,
    binary: str | None = None,
    timeout_seconds: int = 1200,
) -> dict[str, Any]:
    if role not in {"planner_deep", "implementer_fast", "implementer_recovery", "reviewer_deep"}:
        raise ValueError(f"unsupported role: {role}")
    config = capability(host)
    role_config = config.get("externalRoles", config["roles"])[role]
    model = role_config["model"]
    executable_name = binary or config["binary"]
    executable = shutil.which(executable_name) if os.path.sep not in executable_name else executable_name
    root = Path(run_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not executable or not Path(executable).exists():
        return {"verdict": "BLOCKED", "reason": f"{host.upper()}_CLI_MISSING", "role": role, "requestedModel": model}
    message = prompt or _default_prompt(role, task_path or os.environ.get("PROOFLOOP_TASK_PATH"), root)
    repo = Path(repository).resolve()
    if host == "codex":
        # Planner/reviewer need to write run artifacts under .proofloop. The
        # orchestrator snapshots source before read-only roles and rejects any
        # production mutation, so workspace-write is safe and observable.
        command = [
            str(executable), "exec", "--json", "--ephemeral", "--sandbox", "workspace-write",
            "--model", model, message,
        ]
    elif host == "antigravity":
        command = [str(executable), "--model", model]
        if os.environ.get("PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS") == "1":
            command.append("--dangerously-skip-permissions")
        command.extend(["-p", message])
    elif host == "claude-code":
        command = [
            str(executable), "-p", message, "--model", model,
            "--output-format", "json", "--permission-mode", "bypassPermissions",
        ]
    else:
        return {"verdict": "BLOCKED", "reason": "EXTERNAL_ROLE_RUNNER_NOT_SUPPORTED", "role": role}
    sequence = len(list((root / "invocations").glob("*"))) + 1 if (root / "invocations").exists() else 1
    invocation_id = f"{sequence:02d}-{host}-{role}"
    call_dir = root / "invocations" / invocation_id
    call_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        completed = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        timed_out = False
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        timed_out = True
        exit_code = 124
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes): stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes): stderr = stderr.decode(errors="replace")
    (call_dir / "stdout.log").write_text(stdout, encoding="utf-8")
    (call_dir / "stderr.log").write_text(stderr, encoding="utf-8")
    observed = detect_model(stdout) or detect_model(stderr)
    event = {
        "invocationId": invocation_id,
        "timestampEpoch": started,
        "host": host,
        "role": role,
        "requestedModel": model,
        "expectedModel": model,
        "observedModel": observed,
        "modelEvidence": "HOST_OUTPUT" if observed else "CLI_REQUESTED",
        "command": command,
        "exitCode": exit_code,
        "timedOut": timed_out,
        "durationSeconds": round(time.time() - started, 6),
        "stdoutRef": str(call_dir / "stdout.log"),
        "stderrRef": str(call_dir / "stderr.log"),
    }
    trace = root / "model-trace.jsonl"
    _append(trace, event)
    summary = summarize_trace(trace)
    summary["host"] = host
    summary["capabilityMode"] = "EXTERNAL_MODEL_ROUTING"
    write_json(root / "model-trace-summary.json", summary)
    result = {
        "verdict": "PASS" if exit_code == 0 else "FAIL",
        "role": role,
        "requestedModel": model,
        "observedModel": observed,
        "modelEvidence": event["modelEvidence"],
        "exitCode": exit_code,
        "invocationDir": str(call_dir),
        "invocationId": invocation_id,
        "traceRecorded": True,
    }
    write_json(call_dir / "invocation.json", {**event, **result})
    return result
