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


def load_task_brief(path: str | Path) -> TaskBrief:
    raw = read_json(path)
    checks_raw = raw.get("requiredChecks")
    if not isinstance(checks_raw, list) or not checks_raw:
        raise ValueError("requiredChecks must contain at least one command")
    checks: list[CheckSpec] = []
    for index, item in enumerate(checks_raw):
        if not isinstance(item, dict):
            raise ValueError(f"requiredChecks[{index}] must be an object")
        command = item.get("command")
        if not isinstance(command, list) or not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError(f"requiredChecks[{index}].command must be a non-empty string list")
        timeout = item.get("timeoutSeconds", 300)
        if not isinstance(timeout, int) or timeout <= 0:
            raise ValueError(f"requiredChecks[{index}].timeoutSeconds must be a positive integer")
        cwd = item.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError(f"requiredChecks[{index}].cwd must be a string")
        name = item.get("name")
        if name is not None and not isinstance(name, str):
            raise ValueError(f"requiredChecks[{index}].name must be a string")
        checks.append(CheckSpec(command=list(command), cwd=cwd, timeout_seconds=timeout, name=name))

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

    return TaskBrief(
        task_id=_require_string(raw.get("id"), "id"),
        objective=_require_string(raw.get("objective"), "objective"),
        allowed_paths=_list_of_strings(raw.get("allowedPaths"), "allowedPaths"),
        protected_paths=_list_of_strings(raw.get("protectedPaths"), "protectedPaths"),
        required_checks=tuple(checks),
        change_budget=change_budget,
        simplicity=simplicity,
        max_fast_attempts=fast,
        max_recovery_attempts=recovery,
    )
