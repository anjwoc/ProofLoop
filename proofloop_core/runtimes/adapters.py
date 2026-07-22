from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from proofloop_core.runtimes.acp_runner import invoke_acp_role
from proofloop_core.context.events import EventEmitter
from proofloop_core.runtimes.host_runner import invoke_role
from proofloop_core.runtimes.hosts import probe
from proofloop_core.runtimes.runtime import ResolvedRuntime, RuntimeRegistry
from proofloop_core.analysis.usage import record_normalized_usage
from proofloop_core.runtimes.host_adapter import HostCapability, HostEvent, HostRunHandle, HostResult


@dataclass(frozen=True)
class RoleInvocation:
    role: str
    prompt: str
    repository: Path
    run_dir: Path
    task_path: Path | None = None
    result_path: Path | None = None
    timeout_seconds: int = 1200
    emitter: EventEmitter | None = None
    phase: str = "EXECUTE"
    task_id: str | None = None
    attempt: int | None = None
    runtime: ResolvedRuntime | None = None
    invocation_id: str | None = None


class HostAdapter(Protocol):
    host: str

    def probe(self) -> dict[str, Any]: ...

    def invoke(self, invocation: RoleInvocation) -> dict[str, Any]: ...

    def detect_capabilities(self) -> HostCapability: ...
    def start_role(self, invocation: RoleInvocation) -> HostRunHandle: ...
    def stream_events(self, handle: HostRunHandle) -> Iterator[HostEvent]: ...
    def cancel(self, handle: HostRunHandle) -> None: ...
    def collect_result(self, handle: HostRunHandle) -> HostResult: ...


class ExternalCLIAdapter:
    """Reference adapter that invokes isolated host CLI processes.

    It gives the orchestrator deterministic ownership of role order. Native
    in-session subagents can be added later without changing the kernel.
    """

    def __init__(
        self,
        host: str,
        binary: str | None = None,
        *,
        routing_policy: str = "controller",
        registry: RuntimeRegistry | None = None,
    ):
        self.host = host
        self.binary = binary
        self.routing_policy = routing_policy
        self.registry = registry or RuntimeRegistry()

    def probe(self) -> dict[str, Any]:
        result = probe(self.host)
        configured = result.get("mode")
        if result.get("available"):
            result["mode"] = "ROLE_ROUTING_ONLY" if self.host == "antigravity" else "EXTERNAL_MODEL_ROUTING"
            result["nativeMode"] = configured
        result["routingPolicy"] = self.routing_policy
        result["runtimeCatalog"] = self.registry.catalog()
        return result

    def detect_capabilities(self) -> HostCapability:
        from proofloop_core.runtimes.hosts import capability
        cap = capability(self.host)
        mode = cap.get("mode", "ROLE_ROUTING_ONLY")
        roles = cap.get("roles", {})
        models = tuple(sorted(set(r.get("model") for r in roles.values() if r.get("model"))))
        return HostCapability(
            host_name=self.host,
            version=cap.get("version"),
            supports_streaming=True,
            supports_structured_output=True,
            supports_subagents=self.host == "claude",
            supports_model_selection=mode != "ROLE_ROUTING_ONLY",
            supports_tool_restriction=True,
            supports_session_resume=self.host == "claude",
            supports_json_output=True,
            supports_worktree_isolation=False,
            supports_prompt_injection=True,
            available_models=models,
            limitations=()
        )

    def start_role(self, invocation: RoleInvocation) -> HostRunHandle:
        resolved = invocation.runtime or self.resolve_role(invocation.role)
        invocation_root = invocation.run_dir / "invocations"
        sequence = len(list(invocation_root.glob("*"))) + 1 if invocation_root.exists() else 1
        invocation_id = invocation.invocation_id or f"{sequence:02d}-{resolved.runtime_id}-{invocation.role}"
        return HostRunHandle(
            invocation_id=invocation_id,
            host_name=self.host,
            role=invocation.role,
            internal_state={"invocation": invocation, "resolved": resolved}
        )

    def stream_events(self, handle: HostRunHandle) -> Iterator[HostEvent]:
        yield HostEvent("lifecycle", "Started role execution (synchronous block)", {})

    def cancel(self, handle: HostRunHandle) -> None:
        pass

    def collect_result(self, handle: HostRunHandle) -> HostResult:
        state = handle.internal_state or {}
        invocation = state["invocation"]
        result = self.invoke(invocation)
        return HostResult(payload=result)

    def resolve_role(self, role: str) -> ResolvedRuntime:
        resolved = self.registry.resolve(self.host, role, policy=self.routing_policy)
        if self.binary and resolved.runtime_id == self.host:
            return ResolvedRuntime(
                **{**resolved.to_dict(), "executable": self.binary, "transport": "legacy-cli"}
            )
        return resolved

    def invoke(self, invocation: RoleInvocation) -> dict[str, Any]:
        prompt = invocation.prompt
        if invocation.result_path:
            prompt = prompt.replace(str(invocation.result_path), "the parent-owned result artifact")
            prompt += (
                "\n\nDo not write the role result into .proofloop or any repository file. Return the required JSON between "
                "literal lines PROOFLOOP_RESULT_BEGIN and PROOFLOOP_RESULT_END. The parent process exclusively owns artifact storage."
            )
        resolved = invocation.runtime or self.resolve_role(invocation.role)
        invocation_root = invocation.run_dir / "invocations"
        sequence = len(list(invocation_root.glob("*"))) + 1 if invocation_root.exists() else 1
        invocation_id = invocation.invocation_id or f"{sequence:02d}-{resolved.runtime_id}-{invocation.role}"
        if resolved.transport == "acp":
            call_dir = invocation_root / invocation_id

            def on_event(event_type: str, message: str, data: dict[str, Any]) -> None:
                if event_type == "usage.observed":
                    record_normalized_usage(
                        invocation.run_dir,
                        run_id=invocation.emitter.run_id if invocation.emitter else invocation.run_dir.name,
                        invocation_id=invocation_id,
                        role=invocation.role,
                        runtime=resolved.runtime_id,
                        model=str(data.get("observedModel") or resolved.model),
                        requested_model=resolved.model,
                        task_id=invocation.task_id,
                        phase=invocation.phase,
                        attempt=invocation.attempt,
                        data=data,
                        source="acp",
                    )
                if invocation.emitter is None:
                    return
                invocation.emitter.emit(
                    event_type,
                    phase=invocation.phase,
                    message=message,
                    task_id=invocation.task_id,
                    data={
                        "role": invocation.role,
                        "attempt": invocation.attempt,
                        "invocationId": invocation_id,
                        "runtime": resolved.runtime_id,
                        **data,
                    },
                )

            result = invoke_acp_role(
                resolved,
                invocation.repository,
                call_dir,
                prompt,
                invocation.timeout_seconds,
                on_event,
            )
            normalized = {
                **result,
                "role": invocation.role,
                "runtime": resolved.runtime_id,
                "invocationDir": str(call_dir),
                "invocationId": invocation_id,
                "modelEventEmitted": False,
            }
            return _materialize_parent_artifact(invocation, normalized)
        result = invoke_role(
            resolved.runtime_id,
            invocation.role,
            invocation.repository,
            invocation.run_dir,
            prompt=prompt,
            task_path=str(invocation.task_path) if invocation.task_path else None,
            binary=resolved.executable,
            timeout_seconds=invocation.timeout_seconds,
            emitter=invocation.emitter,
            phase=invocation.phase,
            task_id=invocation.task_id,
            attempt=invocation.attempt,
            model_override=resolved.model,
            access_mode=resolved.access_mode,
            fixed_args=resolved.fixed_args,
            invocation_id=invocation_id,
        )
        result["runtime"] = resolved.runtime_id
        result["routingFallback"] = resolved.fallback
        result["routingReason"] = resolved.reason
        return _materialize_parent_artifact(invocation, result)


def _materialize_parent_artifact(invocation: RoleInvocation, result: dict[str, Any]) -> dict[str, Any]:
    if invocation.result_path is None:
        return result
    payload = _extract_result_payload(Path(str(result.get("invocationDir") or "")), result)
    if payload is None:
        result["artifactOwner"] = "PARENT_PROCESS"
        result["artifactCaptured"] = False
        return result
    invocation.result_path.parent.mkdir(parents=True, exist_ok=True)
    invocation.result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["artifactOwner"] = "PARENT_PROCESS"
    result["artifactCaptured"] = True
    return result


def _extract_result_payload(invocation_dir: Path, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    candidates: list[str] = _nested_strings(result or {})
    for name in ("stdout.log", "stderr.log"):
        path = invocation_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        candidates.append(text)
        for line in text.splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            candidates.extend(_nested_strings(value))
    pattern = re.compile(r"PROOFLOOP_RESULT_BEGIN\s*(.*?)\s*PROOFLOOP_RESULT_END", re.DOTALL)
    for candidate in candidates:
        match = pattern.search(candidate)
        if not match:
            continue
        raw = match.group(1).strip()
        if raw.startswith("```") and raw.endswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def _nested_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _nested_strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _nested_strings(child)]
    return []
