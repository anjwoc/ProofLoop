from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


STRATEGIES = {
    "DIRECT_VERIFIED_CHANGE",
    "PLANNED_IMPLEMENTATION",
    "HIGH_RISK_ENGINEERING",
    "REPOSITORY_ANALYSIS",
}

_HIGH_RISK = re.compile(
    r"\b(payment|billing|money|security|auth(?:entication|orization)?|permission|"
    r"concurren|race condition|idempot|transaction|migration|schema|distributed|"
    r"consistency|encryption|credential|secret|production outage|data loss)\b",
    re.IGNORECASE,
)
_ANALYSIS_ONLY = re.compile(
    r"\b(analy[sz]e|analysis|review|explain|understand|map|architecture|audit)\b",
    re.IGNORECASE,
)
_MUTATION = re.compile(
    r"\b(implement|fix|change|modify|refactor|add|remove|create|update|migrate|"
    r"repair|write|build|develop|developing|수정|구현|개발|추가|삭제|리팩터링)\b",
    re.IGNORECASE,
)
_DIRECT = re.compile(
    r"\b(typo|rename|one[- ]line|single file|small local|obvious|formatting|"
    r"오타|이름만|한 줄|한줄|단순 수정)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StrategyDecision:
    strategy: str
    risk: str
    planner_required: bool
    reviewer_required: bool
    context_required: bool
    reason: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0",
            "strategy": self.strategy,
            "risk": self.risk,
            "plannerRequired": self.planner_required,
            "reviewerRequired": self.reviewer_required,
            "contextRequired": self.context_required,
            "reason": list(self.reason),
        }


def classify_request(request: str, override: str | None = None) -> StrategyDecision:
    text = request.strip()
    if not text:
        raise ValueError("request must be non-empty")
    if override:
        normalized = override.strip().upper().replace("-", "_")
        if normalized not in STRATEGIES:
            raise ValueError(f"unsupported strategy override: {override}")
        return _decision_for(normalized, ("explicit strategy override",))

    analysis = bool(_ANALYSIS_ONLY.search(text))
    mutation = bool(_MUTATION.search(text))
    high_risk = bool(_HIGH_RISK.search(text))
    direct = bool(_DIRECT.search(text)) and len(text) < 500

    if analysis and not mutation:
        return _decision_for("REPOSITORY_ANALYSIS", ("read-only analysis intent detected",))
    if high_risk:
        return _decision_for("HIGH_RISK_ENGINEERING", ("high-risk engineering term detected",))
    if direct:
        return _decision_for("DIRECT_VERIFIED_CHANGE", ("bounded local change signal detected",))
    return _decision_for("PLANNED_IMPLEMENTATION", ("non-trivial mutation defaults to planned execution",))


def _decision_for(strategy: str, reason: tuple[str, ...]) -> StrategyDecision:
    if strategy == "DIRECT_VERIFIED_CHANGE":
        return StrategyDecision(strategy, "low", False, True, False, reason)
    if strategy == "PLANNED_IMPLEMENTATION":
        return StrategyDecision(strategy, "medium", True, True, False, reason)
    if strategy == "HIGH_RISK_ENGINEERING":
        return StrategyDecision(strategy, "high", True, True, False, reason)
    if strategy == "REPOSITORY_ANALYSIS":
        return StrategyDecision(strategy, "medium", True, True, True, reason)
    raise ValueError(f"unsupported strategy: {strategy}")
