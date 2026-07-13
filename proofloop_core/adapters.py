from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .events import EventEmitter
from .host_runner import invoke_role
from .hosts import probe


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


class HostAdapter(Protocol):
    host: str

    def probe(self) -> dict[str, Any]: ...

    def invoke(self, invocation: RoleInvocation) -> dict[str, Any]: ...


class ExternalCLIAdapter:
    """Reference adapter that invokes isolated host CLI processes.

    It gives the orchestrator deterministic ownership of role order. Native
    in-session subagents can be added later without changing the kernel.
    """

    def __init__(self, host: str, binary: str | None = None):
        self.host = host
        self.binary = binary

    def probe(self) -> dict[str, Any]:
        result = probe(self.host)
        configured = result.get("mode")
        if self.host == "antigravity":
            result["nativeMode"] = configured
            result["modelRoutingStatus"] = "ROLE_ROUTING_ONLY"
        elif result.get("available"):
            result["mode"] = "EXTERNAL_MODEL_ROUTING"
            result["nativeMode"] = configured
        return result

    def invoke(self, invocation: RoleInvocation) -> dict[str, Any]:
        prompt = invocation.prompt
        if invocation.result_path:
            prompt += (
                "\n\nWrite the required machine-readable result to this exact absolute path before finishing: "
                f"{invocation.result_path}. Do not write the result anywhere else."
            )
        return invoke_role(
            self.host,
            invocation.role,
            invocation.repository,
            invocation.run_dir,
            prompt=prompt,
            task_path=str(invocation.task_path) if invocation.task_path else None,
            binary=self.binary,
            timeout_seconds=invocation.timeout_seconds,
            emitter=invocation.emitter,
            phase=invocation.phase,
            task_id=invocation.task_id,
            attempt=invocation.attempt,
        )
