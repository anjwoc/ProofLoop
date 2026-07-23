from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class RepairAction(str, Enum):
    RUN_FAST = "RUN_FAST"
    RUN_RECOVERY = "RUN_RECOVERY"
    RETURN_TO_PLANNER = "RETURN_TO_PLANNER"
    REVIEW = "REVIEW"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class RepairState:
    has_attempts: bool
    latest_role: str | None
    latest_check_verdict: str | None
    latest_diff_verdict: str | None
    latest_classification: str | None
    latest_fingerprint: str | None
    previous_fingerprint: str | None
    previous_role: str | None
    evidence_delta: bool
    fast_used: int
    recovery_used: int
    max_fast_attempts: int
    max_recovery_attempts: int

    @classmethod
    def from_attempts(
        cls,
        attempts: list[dict[str, Any]],
        *,
        max_fast_attempts: int,
        max_recovery_attempts: int,
    ) -> "RepairState":
        if max_fast_attempts < 1 or max_recovery_attempts < 0:
            raise ValueError("repair budgets must be explicit and nonnegative")
        if not attempts:
            return cls(
                has_attempts=False,
                latest_role=None,
                latest_check_verdict=None,
                latest_diff_verdict=None,
                latest_classification=None,
                latest_fingerprint=None,
                previous_fingerprint=None,
                previous_role=None,
                evidence_delta=True,
                fast_used=0,
                recovery_used=0,
                max_fast_attempts=max_fast_attempts,
                max_recovery_attempts=max_recovery_attempts,
            )
        latest = attempts[-1]
        previous = attempts[-2] if len(attempts) > 1 else None
        evidence_delta = True
        if previous is not None:
            # Artifact paths are sequence-specific and therefore always change.
            # Progress is semantic only when verdict, classification, or the
            # normalized failure fingerprint changes.
            evidence_delta = any(
                latest.get(field) != previous.get(field)
                for field in (
                    "checkVerdict",
                    "diffVerdict",
                    "classification",
                    "failureFingerprint",
                )
            )
        return cls(
            has_attempts=True,
            latest_role=str(latest.get("role")) if latest.get("role") else None,
            latest_check_verdict=str(latest.get("checkVerdict")) if latest.get("checkVerdict") else None,
            latest_diff_verdict=str(latest.get("diffVerdict")) if latest.get("diffVerdict") else None,
            latest_classification=str(latest.get("classification")) if latest.get("classification") else None,
            latest_fingerprint=str(latest.get("failureFingerprint")) if latest.get("failureFingerprint") else None,
            previous_fingerprint=str(previous.get("failureFingerprint")) if previous and previous.get("failureFingerprint") else None,
            previous_role=str(previous.get("role")) if previous and previous.get("role") else None,
            evidence_delta=evidence_delta,
            fast_used=sum(1 for item in attempts if item.get("role") == "implementer_fast"),
            recovery_used=sum(1 for item in attempts if item.get("role") == "implementer_recovery"),
            max_fast_attempts=max_fast_attempts,
            max_recovery_attempts=max_recovery_attempts,
        )


@dataclass(frozen=True)
class RepairDecision:
    action: RepairAction
    rule_id: str
    reason: str
    consumed_budget: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "ruleId": self.rule_id,
            "reason": self.reason,
            "consumedBudget": self.consumed_budget,
        }


Rule = tuple[str, Callable[[RepairState], bool], Callable[[RepairState], RepairDecision]]
_OWNER_DECISION_CLASSIFICATIONS = {
    "DESIGN_CONFLICT",
    "SPEC_AMBIGUITY",
    "CONTRACT_CHANGE",
    "AUTHORIZATION_AMBIGUOUS",
    "REPOSITORY_FACTS_CONFLICT",
    "REPEATED_FAILURE_INVALIDATES_HYPOTHESIS",
}


def _decision(action: RepairAction, rule_id: str, reason: str, budget: str | None = None) -> RepairDecision:
    return RepairDecision(action=action, rule_id=rule_id, reason=reason, consumed_budget=budget)


def _same_failure_without_delta(state: RepairState) -> bool:
    return bool(
        state.has_attempts
        and state.latest_fingerprint
        and state.latest_fingerprint == state.previous_fingerprint
        and state.latest_role == state.previous_role
        and not state.evidence_delta
    )


_RULES: tuple[Rule, ...] = (
    (
        "R00_INITIAL_FAST",
        lambda state: not state.has_attempts,
        lambda state: _decision(RepairAction.RUN_FAST, "R00_INITIAL_FAST", "no attempts recorded", "fast"),
    ),
    (
        "R10_DETERMINISTIC_SUCCESS",
        lambda state: state.latest_check_verdict == "PASS" and state.latest_diff_verdict == "PASS",
        lambda state: _decision(RepairAction.REVIEW, "R10_DETERMINISTIC_SUCCESS", "deterministic checks and diff guard passed"),
    ),
    (
        "R20_OWNER_DECISION",
        lambda state: state.latest_classification in _OWNER_DECISION_CLASSIFICATIONS,
        lambda state: _decision(
            RepairAction.RETURN_TO_PLANNER,
            "R20_OWNER_DECISION",
            str(state.latest_classification),
            "replan",
        ),
    ),
    (
        "R30_IDENTICAL_FAST_TO_RECOVERY",
        lambda state: _same_failure_without_delta(state)
        and state.latest_role == "implementer_fast"
        and state.recovery_used < state.max_recovery_attempts,
        lambda state: _decision(
            RepairAction.RUN_RECOVERY,
            "R30_IDENTICAL_FAST_TO_RECOVERY",
            "identical fast failure has no evidence delta; same-role retry forbidden",
            "recovery",
        ),
    ),
    (
        "R31_IDENTICAL_FAILURE_BLOCK",
        _same_failure_without_delta,
        lambda state: _decision(
            RepairAction.BLOCKED,
            "R31_IDENTICAL_FAILURE_BLOCK",
            "BLOCKED_IDENTICAL_FAILURE: identical failure has no evidence delta",
        ),
    ),
    (
        "R40_FAST_BUDGET",
        lambda state: state.latest_role == "implementer_fast" and state.fast_used < state.max_fast_attempts,
        lambda state: _decision(RepairAction.RUN_FAST, "R40_FAST_BUDGET", "changed fast failure remains within budget", "fast"),
    ),
    (
        "R50_RECOVERY_BUDGET",
        lambda state: state.recovery_used < state.max_recovery_attempts,
        lambda state: _decision(RepairAction.RUN_RECOVERY, "R50_RECOVERY_BUDGET", "recovery budget remains", "recovery"),
    ),
    (
        "R99_BUDGET_EXHAUSTED",
        lambda state: True,
        lambda state: _decision(RepairAction.BLOCKED, "R99_BUDGET_EXHAUSTED", "all frozen repair budgets are exhausted"),
    ),
)


def decide_state(state: RepairState) -> RepairDecision:
    for _rule_id, predicate, produce in _RULES:
        if predicate(state):
            return produce(state)
    raise AssertionError("repair decision table must be exhaustive")


def decide_next(
    attempts: list[dict[str, Any]],
    max_fast_attempts: int,
    max_recovery_attempts: int,
) -> dict[str, Any]:
    state = RepairState.from_attempts(
        attempts,
        max_fast_attempts=max_fast_attempts,
        max_recovery_attempts=max_recovery_attempts,
    )
    return decide_state(state).to_dict()


def rule_ids() -> tuple[str, ...]:
    return tuple(rule_id for rule_id, _predicate, _produce in _RULES)
