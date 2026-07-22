from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from proofloop_core.runtimes.runtime import ResolvedRuntime


ACPEventCallback = Callable[[str, str, dict[str, Any]], None]


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=False, exclude_none=True)
    if isinstance(value, dict):
        return {str(key): _dump(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_dump(item) for item in value]
    return value


def _first_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        direct = value.get("text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        for item in value.values():
            found = _first_text(item)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _first_text(item)
            if found:
                return found
    return None


def normalize_acp_update(update: Any) -> tuple[str, str, dict[str, Any]]:
    name = type(update).__name__
    payload = _dump(update)
    mapping = {
        "UserMessageChunk": "user_message_chunk",
        "AgentMessageChunk": "agent_message_chunk",
        "AgentThoughtChunk": "agent_thought_chunk",
        "ToolCallStart": "tool_call_started",
        "ToolCallProgress": "tool_call_updated",
        "AgentPlanUpdate": "plan_updated",
        "AgentPlanContentUpdate": "plan_updated",
        "AgentPlanRemovedUpdate": "plan_updated",
        "AvailableCommandsUpdate": "available_commands_updated",
        "CurrentModeUpdate": "current_mode_updated",
        "ConfigOptionUpdate": "config_option_updated",
        "SessionInfoUpdate": "session_info_updated",
        "UsageUpdate": "usage_updated",
    }
    kind = mapping.get(name, "unknown")
    text = _first_text(payload)
    message = text or name
    data = {"kind": kind, "update": payload}
    if kind == "usage_updated" and isinstance(payload, dict):
        used = payload.get("used")
        size = payload.get("size")
        if isinstance(used, (int, float)) and isinstance(size, (int, float)) and size > 0:
            data["contextWindow"] = {
                "used": int(used),
                "size": int(size),
                "ratio": round(float(used) / float(size), 6),
            }
        cost = payload.get("cost")
        if isinstance(cost, dict) and isinstance(cost.get("amount"), (int, float)):
            data["cumulativeCost"] = {
                "amount": float(cost["amount"]),
                "currency": str(cost.get("currency") or ""),
            }
    return "session.update", message, data


def _select_permission(options: list[Any], access_mode: str) -> dict[str, Any]:
    values = [_dump(option) for option in options]
    wanted = ("allow_always", "allow_once") if access_mode == "workspace-write" else (
        "reject_once",
        "reject_always",
    )
    for kind in wanted:
        for option in values:
            if option.get("kind") == kind:
                return {"outcome": {"outcome": "selected", "option_id": option.get("option_id")}}
    return {"outcome": {"outcome": "cancelled"}}


def _find_config_option(options: list[Any] | None, *names: str) -> Any | None:
    normalized_names = {name.lower() for name in names}
    for option in options or []:
        value = _dump(option)
        option_id = str(value.get("id") or value.get("config_id") or "").lower()
        category = str(value.get("category") or "").lower()
        if option_id in normalized_names or category in normalized_names:
            return option
    return None


async def _invoke(
    resolved: ResolvedRuntime,
    repository: Path,
    prompt: str,
    timeout_seconds: float,
    callback: ACPEventCallback,
    stderr_handle: Any,
) -> dict[str, Any]:
    try:
        # ACP is an optional runtime extra. Keep its absence a runtime error
        # with a clear installation instruction, while type-checking the core
        # package without requiring every host SDK to be installed.
        from acp import PROTOCOL_VERSION, spawn_agent_process, text_block  # type: ignore[import-not-found]
        from acp.interfaces import Client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("ACP Python SDK is unavailable; install the 'acp' extra") from exc

    class ProofLoopClient(Client):
        async def request_permission(self, session_id, tool_call, options, **kwargs):
            del session_id, tool_call, kwargs
            return _select_permission(options, resolved.access_mode)

        async def session_update(self, session_id, update, **kwargs):
            del kwargs
            event_type, message, data = normalize_acp_update(update)
            callback(event_type, message, {"sessionId": str(session_id), **data})

    environment = dict(os.environ)
    if resolved.runtime_id == "claude-code":
        environment["ANTHROPIC_MODEL"] = resolved.model
    command = resolved.executable
    args = list(resolved.fixed_args)
    started = time.monotonic()
    async with spawn_agent_process(
        ProofLoopClient(),
        command,
        *args,
        env=environment,
        cwd=repository,
        transport_kwargs={"stderr": stderr_handle},
    ) as (connection, process):
        initialized = await connection.initialize(protocol_version=PROTOCOL_VERSION)
        session = await connection.new_session(cwd=str(repository), mcp_servers=[])
        session_id = str(session.session_id)
        callback(
            "session.started",
            "ACP session started.",
            {
                "sessionId": session_id,
                "runtime": resolved.runtime_id,
                "protocolVersion": initialized.protocol_version,
                "transport": "acp",
            },
        )

        model_option = _find_config_option(session.config_options, "model")
        evidence = "ACP_REQUESTED_ONLY"
        observed_model = None
        if model_option is not None:
            dumped = _dump(model_option)
            config_id = str(dumped.get("id") or dumped.get("config_id") or "model")
            configured = await connection.set_config_option(config_id, session_id, resolved.model)
            configured_option = _find_config_option(
                getattr(configured, "config_options", None),
                "model",
            )
            configured_value = _dump(configured_option).get("current_value") if configured_option else None
            if configured_value == resolved.model:
                evidence = "ACP_SESSION_CONFIG"
                observed_model = resolved.model
        reasoning_option = _find_config_option(session.config_options, "reasoning_effort", "effort", "thought_level")
        if reasoning_option is not None and resolved.reasoning:
            dumped = _dump(reasoning_option)
            config_id = str(dumped.get("id") or dumped.get("config_id") or "reasoning_effort")
            await connection.set_config_option(config_id, session_id, resolved.reasoning)

        modes = _dump(session.modes) if session.modes is not None else {}
        available = modes.get("available_modes") or modes.get("availableModes") or []
        available_ids = {
            str(item.get("id") or item.get("mode_id") or "")
            for item in available
            if isinstance(item, dict)
        }
        requested_mode = None
        if resolved.access_mode == "workspace-write":
            requested_mode = {
                "claude-code": "bypassPermissions",
                "codex": "agent-full-access",
                "agy": "yolo",
            }.get(resolved.runtime_id)
        elif resolved.access_mode == "read-only":
            requested_mode = {"claude-code": "plan", "codex": "read-only", "agy": "plan"}.get(
                resolved.runtime_id
            )
        if requested_mode and requested_mode in available_ids:
            await connection.set_session_mode(session_id, requested_mode)

        if observed_model:
            callback(
                "model.resolved",
                "ACP session model configured.",
                {
                    "sessionId": session_id,
                    "requestedModel": resolved.model,
                    "observedModel": observed_model,
                    "evidenceLevel": evidence,
                },
            )
        response = await asyncio.wait_for(
            connection.prompt(session_id=session_id, prompt=[text_block(prompt)]),
            timeout=timeout_seconds,
        )
        callback(
            "session.completed",
            "ACP session completed.",
            {
                "sessionId": session_id,
                "stopReason": str(response.stop_reason),
                "durationSeconds": round(time.monotonic() - started, 6),
            },
        )
        return {
            "sessionId": session_id,
            "stopReason": str(response.stop_reason),
            "processId": process.pid,
            "modelEvidence": evidence,
            "observedModel": observed_model,
        }


def invoke_acp_role(
    resolved: ResolvedRuntime,
    repository: str | Path,
    run_dir: str | Path,
    prompt: str,
    timeout_seconds: float,
    callback: ACPEventCallback,
) -> dict[str, Any]:
    root = Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    stderr_path = root / "stderr.log"
    stdout_path = root / "stdout.log"
    stdout_path.write_text("ACP protocol updates are recorded in events.jsonl.\n", encoding="utf-8")
    started = time.monotonic()
    timed_out = False
    error: str | None = None
    details: dict[str, Any] = {}
    with stderr_path.open("wb") as stderr_handle:
        try:
            details = asyncio.run(
                _invoke(
                    resolved,
                    Path(repository).resolve(),
                    prompt,
                    timeout_seconds,
                    callback,
                    stderr_handle,
                )
            )
            exit_code = 0
        except TimeoutError:
            timed_out = True
            exit_code = 124
            error = "ACP session timed out"
        except Exception as exc:
            exit_code = 1
            error = f"{type(exc).__name__}: {exc}"
    result = {
        "verdict": "PASS" if exit_code == 0 else "FAIL",
        "requestedModel": resolved.model,
        "observedModel": details.get("observedModel") if exit_code == 0 else None,
        "modelEvidence": details.get("modelEvidence", "UNAVAILABLE"),
        "exitCode": exit_code,
        "timedOut": timed_out,
        "cancelled": False,
        "durationSeconds": round(time.monotonic() - started, 6),
        "stdoutRef": str(stdout_path),
        "stderrRef": str(stderr_path),
        "traceRecorded": False,
        "modelEventEmitted": False,
        "transport": "acp",
        **details,
    }
    if error:
        result["error"] = error
    (root / "invocation.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result
