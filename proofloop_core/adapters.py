from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .acp_runner import invoke_acp_role
from .events import EventEmitter
from .host_runner import invoke_role
from .hosts import probe
from .runtime import ResolvedRuntime, RuntimeRegistry
from .usage import record_normalized_usage


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
        if self.host == "antigravity":
            result["nativeMode"] = configured
            result["modelRoutingStatus"] = "ROLE_ROUTING_ONLY"
        elif result.get("available"):
            result["mode"] = "EXTERNAL_MODEL_ROUTING"
            result["nativeMode"] = configured
        result["routingPolicy"] = self.routing_policy
        result["runtimeCatalog"] = self.registry.catalog()
        return result

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
            prompt += (
                "\n\nWrite the required machine-readable result to this exact absolute path before finishing: "
                f"{invocation.result_path}. Do not write the result anywhere else."
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
            return {
                **result,
                "role": invocation.role,
                "runtime": resolved.runtime_id,
                "invocationDir": str(call_dir),
                "invocationId": invocation_id,
                "modelEventEmitted": False,
            }
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
        return result
