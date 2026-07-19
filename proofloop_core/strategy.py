from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Any


STRATEGIES = {
    "DIRECT_VERIFIED_CHANGE",
    "PLANNED_IMPLEMENTATION",
    "HIGH_RISK_ENGINEERING",
    "REPOSITORY_ANALYSIS",
}

_HIGH_RISK = re.compile(
    r"\b(payment|billing|money|security|auth(?:entication|orization)?|permission|"
    r"concurren\w*|race condition|idempot|transaction|migration|schema|distributed|"
    r"consistency|encryption|credential|secret|production outage|data loss)\b"
    r"|결제|과금|보안|인증|인가|권한|마이그레이션|스키마|데이터 손실|운영 장애|동시성",
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
_COMPLEX = re.compile(
    r"\b(across|cross[- ]cutting|multiple|distributed|architecture|end[- ]to[- ]end|"
    r"api.*(?:worker|database)|worker.*database)\b|여러|전체 시스템|아키텍처|레이어",
    re.IGNORECASE,
)
_UNCERTAIN = re.compile(
    r"\b(unfamiliar|unknown|unclear|investigate|debug|intermittent|flaky)\b|"
    r"처음 보는|원인 불명|불명확|조사|간헐적",
    re.IGNORECASE,
)
_GREENFIELD = re.compile(r"\b(new project|greenfield|from scratch)\b|새 프로젝트|처음부터", re.IGNORECASE)


@dataclass(frozen=True)
class StrategyDecision:
    strategy: str
    risk: str
    planner_required: bool
    reviewer_required: bool
    context_required: bool
    reason: tuple[str, ...]
    tier: str
    explorer_required: bool
    scores: dict[str, int]
    hard_gates: tuple[str, ...]
    repository_signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0",
            "strategy": self.strategy,
            "risk": self.risk,
            "plannerRequired": self.planner_required,
            "reviewerRequired": self.reviewer_required,
            "contextRequired": self.context_required,
            "reason": list(self.reason),
            "tier": self.tier,
            "explorerRequired": self.explorer_required,
            "scores": dict(self.scores),
            "hardGates": list(self.hard_gates),
            "repositorySignals": dict(self.repository_signals),
        }


def classify_request(
    request: str,
    override: str | None = None,
    *,
    repository_signals: dict[str, Any] | None = None,
) -> StrategyDecision:
    text = request.strip()
    if not text:
        raise ValueError("request must be non-empty")
    if override:
        normalized = override.strip().upper().replace("-", "_")
        if normalized not in STRATEGIES:
            raise ValueError(f"unsupported strategy override: {override}")
        return _apply_repository_signals(
            _decision_for(normalized, ("explicit strategy override",), text), repository_signals
        )

    analysis = bool(_ANALYSIS_ONLY.search(text))
    mutation = bool(_MUTATION.search(text))
    high_risk = bool(_HIGH_RISK.search(text))
    direct = bool(_DIRECT.search(text)) and len(text) < 500

    if analysis and not mutation:
        return _apply_repository_signals(_decision_for("REPOSITORY_ANALYSIS", ("read-only analysis intent detected",), text), repository_signals)
    if high_risk:
        return _apply_repository_signals(_decision_for("HIGH_RISK_ENGINEERING", ("high-risk engineering term detected",), text), repository_signals)
    if direct:
        return _apply_repository_signals(_decision_for("DIRECT_VERIFIED_CHANGE", ("bounded local change signal detected",), text), repository_signals)
    return _apply_repository_signals(_decision_for("PLANNED_IMPLEMENTATION", ("non-trivial mutation defaults to planned execution",), text), repository_signals)


def _decision_for(strategy: str, reason: tuple[str, ...], text: str) -> StrategyDecision:
    risk_score = 3 if _HIGH_RISK.search(text) else 0
    complexity_score = 2 if _COMPLEX.search(text) or _GREENFIELD.search(text) else (0 if _DIRECT.search(text) else 1)
    uncertainty_score = 2 if _UNCERTAIN.search(text) else 0
    scores = {"risk": risk_score, "complexity": complexity_score, "uncertainty": uncertainty_score}
    hard_gates = ("HIGH_RISK_DOMAIN",) if risk_score >= 3 else (("GREENFIELD_PROJECT",) if _GREENFIELD.search(text) else ())
    if strategy == "REPOSITORY_ANALYSIS":
        tier = "T2"
    elif risk_score >= 3:
        tier = "T3"
    elif strategy == "DIRECT_VERIFIED_CHANGE" and sum(scores.values()) <= 1:
        tier = "T0"
    elif complexity_score >= 2 or uncertainty_score >= 2 or sum(scores.values()) >= 4:
        tier = "T2"
    else:
        tier = "T1"
    if strategy == "DIRECT_VERIFIED_CHANGE":
        return StrategyDecision(strategy, "low", False, False, False, reason, tier, False, scores, hard_gates)
    if strategy == "PLANNED_IMPLEMENTATION":
        planner = tier in {"T2", "T3"}
        reviewer = tier in {"T2", "T3"}
        explorer = tier == "T3" or uncertainty_score >= 2
        return StrategyDecision(strategy, "medium", planner, reviewer, False, reason, tier, explorer, scores, hard_gates)
    if strategy == "HIGH_RISK_ENGINEERING":
        return StrategyDecision(strategy, "high", True, True, False, reason, "T3", True, scores, hard_gates)
    if strategy == "REPOSITORY_ANALYSIS":
        return StrategyDecision(strategy, "medium", True, True, True, reason, "T2", True, scores, hard_gates)
    raise ValueError(f"unsupported strategy: {strategy}")


def reclassify_after_diff(decision: StrategyDecision, changed_paths: list[str]) -> StrategyDecision:
    paths = sorted({path.strip("/") for path in changed_paths if path.strip("/")})
    if not paths:
        return decision
    roots = {path.split("/", 1)[0] for path in paths}
    critical = any(
        re.search(r"(?:auth|permission|payment|billing|migration|schema|deploy|infra|security)", path, re.I)
        for path in paths
    )
    cross_cutting = len(roots) >= 3 or len(paths) >= 4
    if critical:
        tier = "T3"
        gate = "FIRST_DIFF_HIGH_RISK_PATH"
    elif cross_cutting and decision.tier in {"T0", "T1"}:
        tier = "T2"
        gate = "FIRST_DIFF_CROSS_CUTTING"
    elif len(paths) >= 2 and decision.tier == "T0":
        tier = "T1"
        gate = "FIRST_DIFF_SCOPE_EXPANDED"
    else:
        return decision
    strategy = "HIGH_RISK_ENGINEERING" if tier == "T3" else "PLANNED_IMPLEMENTATION"
    return StrategyDecision(
        strategy=strategy,
        risk="high" if tier == "T3" else "medium",
        planner_required=decision.planner_required,
        reviewer_required=tier in {"T2", "T3"},
        context_required=decision.context_required,
        reason=(*decision.reason, "first diff changed the workload profile"),
        tier=tier,
        explorer_required=decision.explorer_required,
        scores=dict(decision.scores),
        hard_gates=(*decision.hard_gates, gate),
        repository_signals=dict(decision.repository_signals),
    )


def _apply_repository_signals(
    decision: StrategyDecision, signals: dict[str, Any] | None
) -> StrategyDecision:
    observed = dict(signals or {})
    if not observed:
        return decision
    critical = bool(observed.get("criticalPath"))
    public_or_state = bool(observed.get("publicContract")) or bool(observed.get("persistentState"))
    broad = int(observed.get("targetFileCount", 0)) >= 4
    unknown_tests = int(observed.get("targetFileCount", 0)) > 0 and int(observed.get("matchingTestCount", 0)) == 0
    if critical:
        tier = "T3"
        gate = "REPOSITORY_CRITICAL_PATH"
    elif public_or_state or broad:
        tier = "T2" if decision.tier in {"T0", "T1"} else decision.tier
        gate = "REPOSITORY_CONTRACT_OR_SCOPE"
    elif unknown_tests and decision.tier == "T0":
        tier = "T1"
        gate = "TARGET_WITHOUT_MAPPED_TEST"
    else:
        return replace(decision, repository_signals=observed)
    return replace(
        decision,
        strategy="HIGH_RISK_ENGINEERING" if tier == "T3" else "PLANNED_IMPLEMENTATION",
        risk="high" if tier == "T3" else decision.risk,
        tier=tier,
        planner_required=tier in {"T2", "T3"},
        reviewer_required=tier in {"T2", "T3"},
        explorer_required=tier == "T3" or (unknown_tests and tier == "T2"),
        reason=(*decision.reason, "repository facts adjusted workload profile"),
        hard_gates=(*decision.hard_gates, gate),
        repository_signals=observed,
    )
