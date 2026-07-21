from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import read_json


SIMPLICITY_RUNGS = {
    "SKIP_NOT_NEEDED",
    "REUSE_EXISTING",
    "STDLIB",
    "PLATFORM_NATIVE",
    "INSTALLED_DEPENDENCY",
    "DIRECT_CHANGE",
    "MINIMAL_NEW_CODE",
}


@dataclass(frozen=True)
class CheckSpec:
    command: list[str]
    cwd: str | None = None
    timeout_seconds: int = 300
    name: str | None = None


@dataclass(frozen=True)
class ChangeBudget:
    max_changed_files: int
    max_added_lines: int
    max_new_files: int
    allow_dependency_changes: bool


@dataclass(frozen=True)
class SimplicityPlan:
    selected_rung: str
    rationale: str
    considered: tuple[str, ...]


@dataclass(frozen=True)
class SurfaceScenario:
    scenario_id: str
    invocation: str
    observable: str
    pass_rule: str
    artifact_type: str
    cleanup: str | None
    command: list[str]
    cwd: str | None = None
    timeout_seconds: int = 300


@dataclass(frozen=True)
class ProofPlan:
    baseline_checks: tuple[CheckSpec, ...]
    red_checks: tuple[CheckSpec, ...]
    automated_checks: tuple[CheckSpec, ...]
    surface_scenarios: tuple[SurfaceScenario, ...]
    adversarial_checks: tuple[CheckSpec, ...]
    cleanup_checks: tuple[CheckSpec, ...]


@dataclass(frozen=True)
class TaskBrief:
    task_id: str
    objective: str
    allowed_paths: tuple[str, ...]
    protected_paths: tuple[str, ...]
    required_checks: tuple[CheckSpec, ...]
    change_budget: ChangeBudget
    simplicity: SimplicityPlan
    max_fast_attempts: int = 2
    max_recovery_attempts: int = 1

    title: str = ""
    criterion_ids: tuple[str, ...] = ()
    deliverables: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    interfaces: tuple[str, ...] = ()
    context_refs: tuple[str, ...] = ()
    tool_allowlist: tuple[str, ...] = ()
    proof_plan: ProofPlan | None = None
    stop_when: str = ""
    escalate_on: tuple[str, ...] = ()


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _list_of_strings(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return tuple(value)


def _positive_int(value: Any, field: str, *, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if not isinstance(value, int) or value < minimum:
        op = ">=" if allow_zero else ">="
        raise ValueError(f"{field} must be {op} {minimum}")
    return value


def _parse_check_list(raw_list: Any, field: str) -> tuple[CheckSpec, ...]:
    if raw_list is None:
        return ()
    if not isinstance(raw_list, list):
        raise ValueError(f"{field} must be a list")

    checks: list[CheckSpec] = []
    for index, item in enumerate(raw_list):
        if not isinstance(item, dict):
            raise ValueError(f"{field}[{index}] must be an object")
        command = item.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError(f"{field}[{index}].command must be a non-empty string list")
        timeout = item.get("timeoutSeconds", 300)
        if not isinstance(timeout, int) or timeout <= 0:
            raise ValueError(f"{field}[{index}].timeoutSeconds must be a positive integer")
        cwd = item.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError(f"{field}[{index}].cwd must be a string")
        name = item.get("name")
        if name is not None and not isinstance(name, str):
            raise ValueError(f"{field}[{index}].name must be a string")
        checks.append(CheckSpec(command=list(command), cwd=cwd, timeout_seconds=timeout, name=name))
    return tuple(checks)


def load_task_brief(path: str | Path) -> TaskBrief:
    raw = read_json(path)

    checks_raw = raw.get("requiredChecks")
    if checks_raw is not None and (not isinstance(checks_raw, list) or not checks_raw):
        raise ValueError("requiredChecks must contain at least one command if present")
    checks = _parse_check_list(checks_raw, "requiredChecks")

    budgets = raw.get("budgets") or {}
    if not isinstance(budgets, dict):
        raise ValueError("budgets must be an object")
    fast = budgets.get("maxFastAttempts", 2)
    recovery = budgets.get("maxRecoveryAttempts", 1)
    if not isinstance(fast, int) or fast < 1:
        raise ValueError("budgets.maxFastAttempts must be >= 1")
    if not isinstance(recovery, int) or recovery < 0:
        raise ValueError("budgets.maxRecoveryAttempts must be >= 0")

    change_raw = raw.get("changeBudget")
    if not isinstance(change_raw, dict):
        raise ValueError("changeBudget is required and must be an object")
    allow_dependency_changes = change_raw.get("allowDependencyChanges", False)
    if not isinstance(allow_dependency_changes, bool):
        raise ValueError("changeBudget.allowDependencyChanges must be boolean")
    change_budget = ChangeBudget(
        max_changed_files=_positive_int(change_raw.get("maxChangedFiles"), "changeBudget.maxChangedFiles"),
        max_added_lines=_positive_int(change_raw.get("maxAddedLines"), "changeBudget.maxAddedLines"),
        max_new_files=_positive_int(change_raw.get("maxNewFiles"), "changeBudget.maxNewFiles", allow_zero=True),
        allow_dependency_changes=allow_dependency_changes,
    )

    simplicity_raw = raw.get("simplicity")
    if not isinstance(simplicity_raw, dict):
        raise ValueError("simplicity is required and must be an object")
    selected_rung = _require_string(simplicity_raw.get("selectedRung"), "simplicity.selectedRung")
    if selected_rung not in SIMPLICITY_RUNGS:
        raise ValueError(f"simplicity.selectedRung must be one of {sorted(SIMPLICITY_RUNGS)}")
    simplicity = SimplicityPlan(
        selected_rung=selected_rung,
        rationale=_require_string(simplicity_raw.get("rationale"), "simplicity.rationale"),
        considered=_list_of_strings(simplicity_raw.get("considered"), "simplicity.considered"),
    )

    proof_plan = None
    if "proofPlan" in raw:
        pp_raw = raw["proofPlan"]
        if not isinstance(pp_raw, dict):
            raise ValueError("proofPlan must be an object")

        scenarios_raw = pp_raw.get("surfaceScenarios", [])
        if not isinstance(scenarios_raw, list):
            raise ValueError("proofPlan.surfaceScenarios must be a list")

        scenarios: list[SurfaceScenario] = []
        for i, s in enumerate(scenarios_raw):
            if not isinstance(s, dict):
                raise ValueError(f"proofPlan.surfaceScenarios[{i}] must be an object")
            command = s.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
                raise ValueError(f"proofPlan.surfaceScenarios[{i}].command must be a non-empty string list")
            cleanup = s.get("cleanup")
            if cleanup is not None and not isinstance(cleanup, str):
                raise ValueError(f"proofPlan.surfaceScenarios[{i}].cleanup must be a string or null")
            cwd = s.get("cwd")
            if cwd is not None and not isinstance(cwd, str):
                raise ValueError(f"proofPlan.surfaceScenarios[{i}].cwd must be a string or null")
            timeout = s.get("timeoutSeconds", 300)
            if not isinstance(timeout, int) or timeout <= 0:
                raise ValueError(f"proofPlan.surfaceScenarios[{i}].timeoutSeconds must be a positive integer")
            scenarios.append(SurfaceScenario(
                scenario_id=_require_string(s.get("scenario_id"), f"surfaceScenarios[{i}].scenario_id"),
                invocation=_require_string(s.get("invocation"), f"surfaceScenarios[{i}].invocation"),
                observable=_require_string(s.get("observable"), f"surfaceScenarios[{i}].observable"),
                pass_rule=_require_string(s.get("pass_rule"), f"surfaceScenarios[{i}].pass_rule"),
                artifact_type=_require_string(s.get("artifact_type"), f"surfaceScenarios[{i}].artifact_type"),
                cleanup=cleanup,
                command=list(command),
                cwd=cwd,
                timeout_seconds=timeout,
            ))

        proof_plan = ProofPlan(
            baseline_checks=_parse_check_list(pp_raw.get("baselineChecks"), "proofPlan.baselineChecks"),
            red_checks=_parse_check_list(pp_raw.get("redChecks"), "proofPlan.redChecks"),
            automated_checks=_parse_check_list(pp_raw.get("automatedChecks"), "proofPlan.automatedChecks"),
            surface_scenarios=tuple(scenarios),
            adversarial_checks=_parse_check_list(pp_raw.get("adversarialChecks"), "proofPlan.adversarialChecks"),
            cleanup_checks=_parse_check_list(pp_raw.get("cleanupChecks"), "proofPlan.cleanupChecks"),
        )

    return TaskBrief(
        task_id=_require_string(raw.get("id"), "id"),
        objective=_require_string(raw.get("objective"), "objective"),
        allowed_paths=_list_of_strings(raw.get("allowedPaths"), "allowedPaths"),
        protected_paths=_list_of_strings(raw.get("protectedPaths"), "protectedPaths"),
        required_checks=checks,
        change_budget=change_budget,
        simplicity=simplicity,
        max_fast_attempts=fast,
        max_recovery_attempts=recovery,

        title=raw.get("title", ""),
        criterion_ids=_list_of_strings(raw.get("criterion_ids"), "criterion_ids"),
        deliverables=_list_of_strings(raw.get("deliverables"), "deliverables"),
        dependencies=_list_of_strings(raw.get("dependencies"), "dependencies"),
        interfaces=_list_of_strings(raw.get("interfaces"), "interfaces"),
        context_refs=_list_of_strings(raw.get("context_refs"), "context_refs"),
        tool_allowlist=_list_of_strings(raw.get("tool_allowlist"), "tool_allowlist"),
        proof_plan=proof_plan,
        stop_when=raw.get("stop_when", ""),
        escalate_on=_list_of_strings(raw.get("escalate_on"), "escalate_on"),
    )
