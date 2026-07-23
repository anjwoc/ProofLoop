from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any



TERMINAL_GOAL_STATES = {"CONVERGED", "EXHAUSTED", "BLOCKED", "CANCELED"}

GOAL_TRANSITIONS: dict[str, set[str]] = {
    "INIT": {"EXPLORE", "DESIGN", "IMPLEMENT", "BLOCKED", "CANCELED"},
    "EXPLORE": {"DESIGN", "BLOCKED", "CANCELED"},
    "DESIGN": {"PLAN_REVIEW", "IMPLEMENT", "BLOCKED", "CANCELED"},
    "PLAN_REVIEW": {"IMPLEMENT", "DESIGN", "BLOCKED", "CANCELED"},
    "IMPLEMENT": {"VERIFY", "BLOCKED", "CANCELED"},
    "VERIFY": {"IMPLEMENT", "TRIAGE", "DEEP_REVIEW", "EXHAUSTED", "BLOCKED", "CANCELED"},
    "TRIAGE": {"IMPLEMENT", "DESIGN", "EXHAUSTED", "BLOCKED", "CANCELED"},
    "DEEP_REVIEW": {"CONVERGED", "TRIAGE", "DESIGN", "EXHAUSTED", "BLOCKED", "CANCELED"},
    "CONVERGED": set(),
    "EXHAUSTED": set(),
    "BLOCKED": set(),
    "CANCELED": set(),
}


@dataclass(frozen=True)
class GoalCriterion:
    criterion_id: str
    description: str
    evidence_kind: str


@dataclass(frozen=True)
class GoalContract:
    request: str
    criteria: tuple[GoalCriterion, ...]
    max_cycles: int
    max_replans: int

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schemaVersion"] = "1.0"
        return value


def build_goal_contract(request: str, tasks: list[Any], *, max_cycles: int = 8, max_replans: int = 2) -> GoalContract:
    criteria: list[GoalCriterion] = [
        GoalCriterion("SC-REQUEST", request.strip(), "DEEP_REVIEW"),
    ]
    for task in tasks:
        criteria.append(GoalCriterion(f"SC-{task.task_id}", task.objective, "TASK_CHECKS"))
        for index, check in enumerate(task.required_checks, start=1):
            name = check.name or " ".join(check.command)
            criteria.append(GoalCriterion(f"SC-{task.task_id}-CHECK-{index}", name, "COMMAND_EXIT"))
    return GoalContract(request.strip(), tuple(criteria), max_cycles, max_replans)

