from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from proofloop_core.context.events import EventEmitter
from proofloop_core.runtimes.hosts import capability
from proofloop_core.context.io import write_json, append_jsonl
from proofloop_core.output_parsers import parser_for
from proofloop_core.runtimes.process_runner import ProcessRunner
from proofloop_core.runtimes.runtime import ACCOUNT_DEFAULT_MODEL
from proofloop_core.context.trace import summarize_trace
from proofloop_core.analysis.usage import TokenLedger, load_invocations, record_normalized_usage

_MAX_HOST_OUTPUT_EVENT_CHARS = 4000
_PRIVATE_REASONING_KEYS = frozenset({"thinking", "signature"})
# Goalng's production AGY adapter normalizes routing IDs to the labels that
# AGY accepts in ``--model``.  Keep ProofLoop's durable traces in canonical
# IDs while using the proven CLI representation at process boundaries.
_AGY_MODEL_LABELS = {
    "gemini-3.5-flash-medium": "Gemini 3.5 Flash (Medium)",
    "gemini-3.5-flash-high": "Gemini 3.5 Flash (High)",
    "gemini-3.5-flash-low": "Gemini 3.5 Flash (Low)",
    "gemini-3.1-pro-low": "Gemini 3.1 Pro (Low)",
    "gemini-3.1-pro-high": "Gemini 3.1 Pro (High)",
}


def _agy_initial_output_timeout_seconds() -> int:
    """Bound AGY's silent-start failure mode without shortening valid runs.

    AGY can remain connected while emitting neither a response nor an error.
    Goalng handles the same provider behaviour separately.  A first-byte cap
    prevents a detached ProofLoop role from spending the whole run budget in
    that state; callers can raise it deliberately for unusually large work.
    """
    raw = os.environ.get("PROOFLOOP_AGY_INITIAL_OUTPUT_TIMEOUT_SECONDS", "90")
    try:
        value = int(raw)
    except ValueError:
        return 90
    return max(15, value)



def _redact_private_reasoning_log(path: Path) -> None:
    """Remove provider reasoning blocks before the raw host transcript persists.

    The observable run contract exposes actions, artifacts, model evidence, and
    concise status—not private reasoning.  Claude's stream-json protocol puts
    reasoning in ``type: thinking`` blocks; retain a structural marker so the
    transcript remains valid JSONL without retaining its content or signature.
    """
    if not path.is_file():
        return
    redacted_lines: list[str] = []
    changed = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            redacted_lines.append(line)
            continue
        cleaned = _without_private_reasoning(value)
        changed = changed or cleaned != value
        redacted_lines.append(json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")))
    if changed:
        path.write_text("\n".join(redacted_lines) + ("\n" if redacted_lines else ""), encoding="utf-8")


def _without_private_reasoning(value: Any) -> Any:
    if isinstance(value, list):
        return [_without_private_reasoning(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") == "thinking":
        return {"type": "thinking", "redacted": True}
    return {
        key: _without_private_reasoning(item)
        for key, item in value.items()
        if key not in _PRIVATE_REASONING_KEYS
    }


def _sanitize_persisted_host_line(_stream_name: str, line: str) -> str:
    """Redact private provider reasoning before a role transcript is written.

    Parser callbacks still receive the original line so model, usage, and tool
    events retain their native shape.  The durable log is the user-facing
    artifact, however, and may never contain a thinking block even while a
    role process is still alive.
    """
    ending = "\n" if line.endswith("\n") else ""
    body = line[:-1] if ending else line
    try:
        value = json.loads(body)
    except json.JSONDecodeError:
        return line
    return json.dumps(_without_private_reasoning(value), ensure_ascii=False, separators=(",", ":")) + ending


def _default_prompt(role: str, task_path: str | None, run_dir: Path) -> str:
    role_text = {
        "planner_deep": "Create the smallest evidence-based implementation plan and task brief. Do not edit production code.",
        "implementer_fast": "Implement exactly one approved task with the smallest change. Use TDD and do not claim checks passed.",
        "implementer_recovery": "Fix the root cause using the exact failure evidence. Do not broaden the task contract.",
        "reviewer_deep": "Independently review the task, real diff, checks, test integrity, claims, and simplicity. Do not edit code.",
        "classifier_fast": "Fast JSON-only intent classifier for routing requests.",
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
    invocation_id: str | None = None,
) -> dict[str, Any]:
    if role not in {"planner_deep", "explorer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep", "classifier_fast"}:
        raise ValueError(f"unsupported role: {role}")
    config = capability(host)
    role_table = config.get("externalRoles", config["roles"])
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
        sandbox = "read-only" if access_mode == "read-only" else "workspace-write"
        command = [
            str(executable), *fixed_args, "exec", "--json", "--ephemeral", "--sandbox", sandbox,
        ]
        if model != ACCOUNT_DEFAULT_MODEL:
            command.extend(["--model", model])
        command.append(message)
    elif host == "claude-code":
        # Role children receive all necessary ProofLoop artifacts in their
        # prompt. Inheriting a user's global MCP inventory can start dozens of
        # unrelated servers for every role, which delays the run and inflates
        # cache usage without improving the scoped task.
        mcp_config = root / "claude-role-mcp.json"
        write_json(mcp_config, {"mcpServers": {}})
        command = [
            str(executable), *fixed_args, "-p", message, "--model", model,
            "--output-format", "stream-json", "--verbose",
            "--strict-mcp-config", "--mcp-config", str(mcp_config),
        ]
        if access_mode == "read-only":
            # ``plan`` is interactive in Claude Code: a role can stop at
            # ExitPlanMode waiting for a human confirmation.  A ProofLoop
            # child is non-interactive, so deny write tools instead while
            # retaining read/search/Bash capability. The parent additionally
            # enforces the source snapshot after invocation.
            command.extend(["--permission-mode", "dontAsk", "--disallowedTools", "Edit,Write,NotebookEdit"])
        else:
            command.extend(["--permission-mode", "bypassPermissions"])
    elif host == "agy":
        # AGY is not Gemini CLI.  Goalng's production adapter uses this
        # exact prompt/model shape; AGY has no structured-output or
        # approval-mode flag.  Its display model labels are required by the
        # installed client even though ``agy models`` lists canonical IDs.
        command = [str(executable), *fixed_args]
        if os.environ.get("PROOFLOOP_AGY_BYPASS_PERMISSIONS") == "1":
            command.append("--dangerously-skip-permissions")
        command.extend(["--prompt", message, "--model", _AGY_MODEL_LABELS.get(model, model)])
    elif host == "antigravity":
        command = [str(executable), *fixed_args]
        if os.environ.get("PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS") == "1":
            command.append("--dangerously-skip-permissions")
        command.extend(["-p", message])
    else:
        return {"verdict": "BLOCKED", "reason": "EXTERNAL_ROLE_RUNNER_NOT_SUPPORTED", "role": role}
    sequence = len(list((root / "invocations").glob("*"))) + 1 if (root / "invocations").exists() else 1
    invocation_id = invocation_id or f"{sequence:02d}-{host}-{role}"
    call_dir = root / "invocations" / invocation_id
    call_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    parser = parser_for(host)
    observed: str | None = None
    evidence_level = "CLI_REQUESTED_ONLY"
    model_event_emitted = False
    parser_degraded = False
    session_id: str | None = None
    failure_reason_code: str | None = None
    failure_reason: str | None = None

    def on_line(stream_name: str, line: str) -> None:
        nonlocal observed, evidence_level, model_event_emitted, parser_degraded, session_id, failure_reason_code, failure_reason
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
            if item.event_type == "session.started" and isinstance(data.get("sessionId"), str):
                session_id = data["sessionId"]
            if item.event_type == "capability.degraded" and data.get("reasonCode") == "RATE_LIMIT":
                # A provider quota is a recoverable external block, not an
                # implementation failure and not evidence that the role's
                # work was incorrect.
                failure_reason_code = "HOST_RATE_LIMITED"
                failure_reason = str(data.get("hostMessage") or item.message)
            if failure_reason_code == "HOST_RATE_LIMITED" and item.event_type == "session.update":
                candidate = str(data.get("text") or "")
                if candidate and ("limit" in candidate.lower() or "429" in candidate):
                    failure_reason = candidate
            if item.event_type == "usage.observed":
                if not data.get("sessionId") and session_id:
                    data["sessionId"] = session_id
                record_normalized_usage(
                    root,
                    run_id=emitter.run_id if emitter else root.name,
                    invocation_id=invocation_id,
                    role=role,
                    runtime=host,
                    model=observed or model,
                    requested_model=model,
                    task_id=task_id,
                    phase=phase,
                    attempt=attempt,
                    data=data,
                    source="host_stream",
                )
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

    initial_output_timeout = _agy_initial_output_timeout_seconds() if host == "agy" else None
    process_result = ProcessRunner().run(
        command,
        cwd=repo,
        stdout_path=call_dir / "stdout.log",
        stderr_path=call_dir / "stderr.log",
        # The parent owns the run-level Truth report. A child role must be
        # allowed to stop once it returns its role result, rather than being
        # re-prompted by an installed Stop hook for a report it cannot create.
        env={**os.environ, "PROOFLOOP_ROLE_CHILD": "1"},
        timeout_seconds=timeout_seconds,
        initial_output_timeout_seconds=initial_output_timeout,
        on_line=on_line,
        output_filter=_sanitize_persisted_host_line,
        stdin_data=None,
        on_heartbeat=on_heartbeat if emitter is not None else None,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )
    _redact_private_reasoning_log(call_dir / "stdout.log")
    _redact_private_reasoning_log(call_dir / "stderr.log")
    if process_result.timed_out and process_result.timeout_reason == "INITIAL_OUTPUT_TIMEOUT":
        failure_reason_code = "HOST_INITIAL_OUTPUT_TIMEOUT"
        failure_reason = (
            f"AGY produced no stdout or stderr within {initial_output_timeout}s; "
            "the invocation was terminated to preserve the run budget."
        )
    if host == "codex":
        headless = root / "usage" / "tokscale-headless" / "codex" / f"{invocation_id}.jsonl"
        headless.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(call_dir / "stdout.log", headless)
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
        "timeoutReason": process_result.timeout_reason,
        "cancelled": process_result.cancelled,
        "transport": "legacy-cli",
        "durationSeconds": process_result.duration_seconds,
        "sessionId": session_id,
        "stdoutRef": process_result.stdout_ref,
        "stderrRef": process_result.stderr_ref,
    }
    trace = root / "model-trace.jsonl"
    append_jsonl(trace, event)
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
        "sessionId": session_id,
        "traceRecorded": True,
        "modelEventEmitted": model_event_emitted,
        "timedOut": process_result.timed_out,
        "timeoutReason": process_result.timeout_reason,
        "cancelled": process_result.cancelled,
        "reasonCode": failure_reason_code,
        "reason": failure_reason,
    }
    write_json(call_dir / "invocation.json", {**event, **result})
    usage_summary = TokenLedger(root).summarize(
        [*load_invocations(root), {"invocationId": invocation_id}]
    )
    usage = next(
        (item for item in usage_summary["byInvocation"] if item["invocationId"] == invocation_id),
        None,
    )
    if usage:
        result["usage"] = usage
        write_json(call_dir / "invocation.json", {**event, **result})
    return result
