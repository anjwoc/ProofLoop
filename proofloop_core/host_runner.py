from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from .events import EventEmitter
from .hosts import capability, role_only_trace_summary
from .io import write_json
from .output_parsers import parser_for
from .process_runner import ProcessRunner
from .trace import summarize_trace

_MAX_HOST_OUTPUT_EVENT_CHARS = 4000


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
    *,
    emitter: EventEmitter | None = None,
    phase: str = "EXECUTE",
    task_id: str | None = None,
    attempt: int | None = None,
    heartbeat_interval_seconds: float = 5.0,
    model_override: str | None = None,
    access_mode: str | None = None,
    fixed_args: tuple[str, ...] = (),
) -> dict[str, Any]:
    if role not in {"planner_deep", "explorer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep"}:
        raise ValueError(f"unsupported role: {role}")
    config = capability(host)
    role_table = config["roles"] if host == "antigravity" else config.get("externalRoles", config["roles"])
    role_config = role_table[role]
    model = model_override or role_config["model"]
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
            str(executable), *fixed_args, "exec", "--json", "--ephemeral", "--sandbox", "workspace-write",
            "--model", model, message,
        ]
    elif host == "antigravity":
        command = [str(executable), *fixed_args]
        if os.environ.get("PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS") == "1":
            command.append("--dangerously-skip-permissions")
        command.extend(["-p", message])
    elif host == "claude-code":
        command = [
            str(executable), *fixed_args, "-p", message, "--model", model,
            "--output-format", "stream-json", "--verbose",
            "--permission-mode", "plan" if access_mode == "read-only" else "bypassPermissions",
        ]
    elif host == "gemini":
        command = [
            str(executable), *fixed_args, "-p", message, "--model", model,
            "--output-format", "stream-json", "--approval-mode",
            "plan" if access_mode == "read-only" else "yolo",
        ]
    else:
        return {"verdict": "BLOCKED", "reason": "EXTERNAL_ROLE_RUNNER_NOT_SUPPORTED", "role": role}
    sequence = len(list((root / "invocations").glob("*"))) + 1 if (root / "invocations").exists() else 1
    invocation_id = f"{sequence:02d}-{host}-{role}"
    call_dir = root / "invocations" / invocation_id
    call_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    parser = parser_for(host)
    observed: str | None = None
    evidence_level = "UNAVAILABLE" if host == "antigravity" else "CLI_REQUESTED_ONLY"
    model_event_emitted = False
    parser_degraded = False

    def on_line(stream_name: str, line: str) -> None:
        nonlocal observed, evidence_level, model_event_emitted, parser_degraded
        visible_text = line.rstrip("\r\n")
        try:
            normalized = parser.feed(stream_name, line)
        except Exception as exc:
            if parser_degraded:
                return
            parser_degraded = True
            evidence_level = "UNAVAILABLE"
            if emitter is not None:
                emitter.emit(
                    "capability.degraded",
                    phase=phase,
                    message="Host output parser failed.",
                    level="warning",
                    task_id=task_id,
                    data={
                        "role": role,
                        "invocationId": invocation_id,
                        "reasonCode": "OUTPUT_PARSER_FAILED",
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            return
        if emitter is not None and visible_text and not normalized:
            structured = False
            try:
                structured = isinstance(json.loads(visible_text), dict)
            except (json.JSONDecodeError, TypeError):
                pass
            if not structured:
                emitter.emit(
                    "role.output",
                    phase=phase,
                    message=f"{role} produced {stream_name} output.",
                    task_id=task_id,
                    data={
                        "role": role,
                        "attempt": attempt,
                        "invocationId": invocation_id,
                        "stream": stream_name,
                        "text": visible_text[:_MAX_HOST_OUTPUT_EVENT_CHARS],
                        "truncated": len(visible_text) > _MAX_HOST_OUTPUT_EVENT_CHARS,
                        "stdoutRef": str(call_dir / "stdout.log"),
                        "stderrRef": str(call_dir / "stderr.log"),
                    },
                )
        for item in normalized:
            data = {
                "role": role,
                "attempt": attempt,
                "requestedModel": model,
                "invocationId": invocation_id,
                "stream": stream_name,
                **item.data,
            }
            if item.event_type == "role.model_observed":
                candidate = data.get("observedModel")
                if not isinstance(candidate, str) or not candidate or observed is not None:
                    continue
                observed = candidate
                evidence_level = str(data.get("evidenceLevel") or "HOST_OUTPUT")
            if emitter is not None:
                emitter.emit(
                    item.event_type,
                    phase=phase,
                    message=item.message,
                    level=item.level,
                    task_id=task_id,
                    data=data,
                )
                if item.event_type == "role.model_observed":
                    model_event_emitted = True

    def on_heartbeat(process_id: int, elapsed_seconds: float) -> None:
        if emitter is None:
            return
        emitter.emit(
            "role.progress",
            phase=phase,
            message=f"{role} is still running.",
            task_id=task_id,
            data={
                "role": role,
                "attempt": attempt,
                "invocationId": invocation_id,
                "processId": process_id,
                "elapsedSeconds": round(elapsed_seconds, 1),
                "stdoutRef": str(call_dir / "stdout.log"),
                "stderrRef": str(call_dir / "stderr.log"),
            },
        )

    process_result = ProcessRunner().run(
        command,
        cwd=repo,
        stdout_path=call_dir / "stdout.log",
        stderr_path=call_dir / "stderr.log",
        timeout_seconds=timeout_seconds,
        on_line=on_line,
        stdin_data=None,
        on_heartbeat=on_heartbeat if emitter is not None else None,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )
    if observed is None and emitter is not None:
        emitter.emit(
            "role.model_observed",
            phase=phase,
            message="Requested model could not be observed.",
            level="warning",
            task_id=task_id,
            data={
                "role": role,
                "attempt": attempt,
                "requestedModel": model,
                "observedModel": None,
                "evidenceLevel": evidence_level,
                "invocationId": invocation_id,
            },
        )
        model_event_emitted = True
    event = {
        "invocationId": invocation_id,
        "timestampEpoch": started,
        "host": host,
        "role": role,
        "requestedModel": model,
        "expectedModel": model,
        "observedModel": observed,
        "modelEvidence": evidence_level,
        "command": command,
        "exitCode": process_result.exit_code,
        "timedOut": process_result.timed_out,
        "cancelled": process_result.cancelled,
        "transport": "legacy-cli",
        "durationSeconds": process_result.duration_seconds,
        "stdoutRef": process_result.stdout_ref,
        "stderrRef": process_result.stderr_ref,
    }
    trace = root / "model-trace.jsonl"
    _append(trace, event)
    if host == "antigravity":
        summary = role_only_trace_summary(host)
    else:
        summary = summarize_trace(trace)
        summary["host"] = host
        summary["capabilityMode"] = "EXTERNAL_MODEL_ROUTING"
    write_json(root / "model-trace-summary.json", summary)
    result = {
        "verdict": "PASS" if process_result.exit_code == 0 else "FAIL",
        "role": role,
        "requestedModel": model,
        "observedModel": observed,
        "modelEvidence": event["modelEvidence"],
        "exitCode": process_result.exit_code,
        "invocationDir": str(call_dir),
        "invocationId": invocation_id,
        "traceRecorded": True,
        "modelEventEmitted": model_event_emitted,
        "timedOut": process_result.timed_out,
        "cancelled": process_result.cancelled,
    }
    write_json(call_dir / "invocation.json", {**event, **result})
    return result
