from __future__ import annotations

import importlib.util
import json
import os
import shutil
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Launcher:
    command: str
    args: tuple[str, ...] = ()
    probe_args: tuple[str, ...] = ("--version",)


@dataclass(frozen=True)
class RuntimeSpec:
    runtime_id: str
    display_name: str
    launcher: Launcher
    cli_output_format: str
    supports_acp: bool = False
    acp_launcher: Launcher | None = None
    model_env_var: str | None = None
    full_access_mode: str | None = None
    read_only_mode: str | None = None


@dataclass(frozen=True)
class RoleRoute:
    runtime_id: str
    model: str
    reasoning: str | None
    access_mode: str


@dataclass(frozen=True)
class ResolvedRuntime:
    controller_host: str
    role: str
    runtime_id: str
    model: str
    reasoning: str | None
    access_mode: str
    transport: str
    executable: str
    fixed_args: tuple[str, ...]
    fallback: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RUNTIME_SPECS: dict[str, RuntimeSpec] = {
    "claude-code": RuntimeSpec(
        runtime_id="claude-code",
        display_name="Claude Code",
        launcher=Launcher("claude"),
        cli_output_format="stream-json",
        supports_acp=True,
        acp_launcher=Launcher("claude-agent-acp"),
        model_env_var="ANTHROPIC_MODEL",
        full_access_mode="bypassPermissions",
        read_only_mode="plan",
    ),
    "codex": RuntimeSpec(
        runtime_id="codex",
        display_name="Codex",
        launcher=Launcher("codex"),
        cli_output_format="jsonl",
        supports_acp=True,
        acp_launcher=Launcher("codex-acp"),
        full_access_mode="agent-full-access",
        read_only_mode="read-only",
    ),
    "gemini": RuntimeSpec(
        runtime_id="gemini",
        display_name="Gemini CLI",
        launcher=Launcher("gemini"),
        cli_output_format="stream-json",
        supports_acp=True,
        acp_launcher=Launcher("gemini", ("--acp",)),
        full_access_mode="yolo",
        read_only_mode="plan",
    ),
    "antigravity": RuntimeSpec(
        runtime_id="antigravity",
        display_name="Antigravity",
        launcher=Launcher("agy"),
        cli_output_format="text",
    ),
}


CONTROLLER_ROUTES: dict[str, dict[str, RoleRoute]] = {
    "claude-code": {
        "planner_deep": RoleRoute("claude-code", "opus", "high", "read-only"),
        "explorer_fast": RoleRoute("claude-code", "haiku", "low", "read-only"),
        "implementer_fast": RoleRoute("claude-code", "haiku", "medium", "workspace-write"),
        "implementer_recovery": RoleRoute("claude-code", "sonnet", "high", "workspace-write"),
        "reviewer_deep": RoleRoute("claude-code", "fable", "high", "read-only"),
    },
    "codex": {
        "planner_deep": RoleRoute("codex", "gpt-5.6", "high", "read-only"),
        "explorer_fast": RoleRoute("codex", "gpt-5.6-terra", "low", "read-only"),
        "implementer_fast": RoleRoute("codex", "gpt-5.6-terra", "medium", "workspace-write"),
        "implementer_recovery": RoleRoute("codex", "gpt-5.6", "high", "workspace-write"),
        "reviewer_deep": RoleRoute("codex", "gpt-5.6", "high", "read-only"),
    },
    "gemini": {
        "planner_deep": RoleRoute("gemini", "gemini-3.1-pro-preview", "high", "read-only"),
        "explorer_fast": RoleRoute("gemini", "flash", "low", "read-only"),
        "implementer_fast": RoleRoute("gemini", "flash", "medium", "workspace-write"),
        "implementer_recovery": RoleRoute("gemini", "gemini-3.1-pro-preview", "high", "workspace-write"),
        "reviewer_deep": RoleRoute("gemini", "gemini-3.1-pro-preview", "high", "read-only"),
    },
    "antigravity": {
        role: RoleRoute("antigravity", "current-session-model", None, "host-managed")
        for role in (
            "planner_deep",
            "explorer_fast",
            "implementer_fast",
            "implementer_recovery",
            "reviewer_deep",
        )
    },
}


GOAL_ROUTES: dict[str, tuple[RoleRoute, ...]] = {
    "planner_deep": (
        RoleRoute("claude-code", "opus", "high", "read-only"),
        RoleRoute("claude-code", "fable", "high", "read-only"),
        RoleRoute("codex", "gpt-5.6", "high", "read-only"),
        RoleRoute("gemini", "gemini-3.1-pro-preview", "high", "read-only"),
    ),
    "explorer_fast": (
        RoleRoute("claude-code", "haiku", "low", "read-only"),
        RoleRoute("gemini", "flash", "low", "read-only"),
        RoleRoute("codex", "gpt-5.6-terra", "low", "read-only"),
    ),
    "implementer_fast": (
        RoleRoute("claude-code", "haiku", "medium", "workspace-write"),
        RoleRoute("gemini", "gemini-3.1-pro-preview", "medium", "workspace-write"),
        RoleRoute("codex", "gpt-5.6-terra", "medium", "workspace-write"),
    ),
    "implementer_recovery": (
        RoleRoute("gemini", "gemini-3.1-pro-preview", "high", "workspace-write"),
        RoleRoute("claude-code", "haiku", "high", "workspace-write"),
        RoleRoute("codex", "gpt-5.6", "high", "workspace-write"),
    ),
    "reviewer_deep": (
        RoleRoute("claude-code", "fable", "high", "read-only"),
        RoleRoute("claude-code", "opus", "high", "read-only"),
        RoleRoute("codex", "gpt-5.6", "high", "read-only"),
        RoleRoute("gemini", "gemini-3.1-pro-preview", "high", "read-only"),
    ),
}


def acp_sdk_available() -> bool:
    return importlib.util.find_spec("acp") is not None


def runtime_spec(runtime_id: str) -> RuntimeSpec:
    try:
        return RUNTIME_SPECS[runtime_id]
    except KeyError as exc:
        raise ValueError(f"unsupported runtime: {runtime_id}") from exc


def _configured_goal_routes() -> dict[str, tuple[RoleRoute, ...]]:
    raw = os.environ.get("PROOFLOOP_ROLE_ROUTING_JSON")
    if not raw:
        return GOAL_ROUTES
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("PROOFLOOP_ROLE_ROUTING_JSON must contain an object")
    configured = dict(GOAL_ROUTES)
    for role, candidates in value.items():
        if role not in GOAL_ROUTES or not isinstance(candidates, list) or not candidates:
            raise ValueError(f"invalid role route override: {role}")
        routes: list[RoleRoute] = []
        for item in candidates:
            if not isinstance(item, dict):
                raise ValueError(f"invalid route candidate for {role}")
            runtime_id = str(item.get("runtime") or "")
            runtime_spec(runtime_id)
            model = str(item.get("model") or "")
            if not model:
                raise ValueError(f"model is required for {role}")
            routes.append(
                RoleRoute(
                    runtime_id,
                    model,
                    str(item["reasoning"]) if item.get("reasoning") else None,
                    str(item.get("accessMode") or "workspace-write"),
                )
            )
        configured[role] = tuple(routes)
    return configured


class RuntimeRegistry:
    def resolve(self, controller_host: str, role: str, *, policy: str = "controller") -> ResolvedRuntime:
        if controller_host not in CONTROLLER_ROUTES:
            raise ValueError(f"unsupported controller host: {controller_host}")
        if policy == "controller":
            candidates = (CONTROLLER_ROUTES[controller_host][role],)
        elif policy == "goal":
            candidates = _configured_goal_routes()[role]
        else:
            raise ValueError(f"unsupported routing policy: {policy}")

        for index, route in enumerate(candidates):
            spec = runtime_spec(route.runtime_id)
            executable, transport, fixed_args = self._available_launcher(spec)
            if executable:
                return ResolvedRuntime(
                    controller_host=controller_host,
                    role=role,
                    runtime_id=route.runtime_id,
                    model=route.model,
                    reasoning=route.reasoning,
                    access_mode=route.access_mode,
                    transport=transport,
                    executable=executable,
                    fixed_args=fixed_args,
                    fallback=index > 0,
                    reason="preferred route available" if index == 0 else "preferred runtime unavailable",
                )

        controller_route = CONTROLLER_ROUTES[controller_host][role]
        spec = runtime_spec(controller_host)
        executable = shutil.which(spec.launcher.command) or spec.launcher.command
        return ResolvedRuntime(
            controller_host=controller_host,
            role=role,
            runtime_id=controller_host,
            model=controller_route.model,
            reasoning=controller_route.reasoning,
            access_mode=controller_route.access_mode,
            transport="legacy-cli",
            executable=executable,
            fixed_args=spec.launcher.args,
            fallback=True,
            reason="no configured worker runtime is available",
        )

    @staticmethod
    def _available_launcher(spec: RuntimeSpec) -> tuple[str | None, str, tuple[str, ...]]:
        if spec.supports_acp and spec.acp_launcher and acp_sdk_available():
            acp_executable = shutil.which(spec.acp_launcher.command)
            if acp_executable:
                return acp_executable, "acp", spec.acp_launcher.args
        executable = shutil.which(spec.launcher.command)
        return executable, "legacy-cli", spec.launcher.args

    def catalog(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for spec in RUNTIME_SPECS.values():
            executable, transport, fixed_args = self._available_launcher(spec)
            result.append(
                {
                    "runtime": spec.runtime_id,
                    "displayName": spec.display_name,
                    "available": executable is not None,
                    "executable": executable,
                    "transport": transport if executable else None,
                    "fixedArgs": list(fixed_args),
                    "supportsACP": spec.supports_acp,
                }
            )
        return result
