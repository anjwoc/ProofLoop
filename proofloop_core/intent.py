from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any


_RISK_PATTERNS = {
    "auth": re.compile(r"\b(auth|authentication|authorization|permission|login)\b|인증|인가|권한|로그인", re.I),
    "money": re.compile(r"\b(payment|billing|money|invoice)\b|결제|과금|금전", re.I),
    "data": re.compile(r"\b(migration|schema|data loss|production)\b|마이그레이션|스키마|데이터 손실|운영", re.I),
    "security": re.compile(r"\b(security|secret|credential|encryption)\b|보안|비밀|자격 증명|암호화", re.I),
}
_UNCERTAINTY = re.compile(r"\b(appropriate|somehow|as needed|if needed|unknown|unclear|maybe)\b|적당히|알아서|필요하면|불명확|모르", re.I)
_TARGET = re.compile(r"(?<![\w/.-])([\w.-]+(?:/[\w.-]+)+|[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|md|json|ya?ml))(?![\w/.-])")


@dataclass(frozen=True)
class AcceptanceCriterion:
    criterion_id: str
    statement: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.criterion_id, "statement": self.statement}


@dataclass(frozen=True)
class IntentContract:
    original_request: str
    original_request_hash: str
    objective: str
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    constraints: tuple[str, ...]
    non_goals: tuple[str, ...]
    authorization_boundary: str
    assumptions: tuple[str, ...]
    unknowns: tuple[str, ...]
    risk_signals: tuple[str, ...]
    target_artifacts: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0",
            "originalRequest": self.original_request,
            "originalRequestHash": self.original_request_hash,
            "objective": self.objective,
            "acceptanceCriteria": [item.to_dict() for item in self.acceptance_criteria],
            "constraints": list(self.constraints),
            "nonGoals": list(self.non_goals),
            "authorizationBoundary": self.authorization_boundary,
            "assumptions": list(self.assumptions),
            "unknowns": list(self.unknowns),
            "riskSignals": list(self.risk_signals),
            "targetArtifacts": list(self.target_artifacts),
        }


def compile_intent(request: str) -> IntentContract:
    if not request.strip():
        raise ValueError("request must be non-empty")
    lines = [line.strip() for line in request.splitlines() if line.strip()]
    objective = _strip_list_marker(lines[0])
    explicit = [_strip_list_marker(line) for line in lines[1:] if _is_list_item(line)]
    criteria_text = _dedupe([objective, *explicit])
    criteria = tuple(
        AcceptanceCriterion(f"AC-{index:03d}", statement)
        for index, statement in enumerate(criteria_text, start=1)
    )
    risk_signals = tuple(name for name, pattern in _RISK_PATTERNS.items() if pattern.search(request))
    unknowns: list[str] = []
    if _UNCERTAINTY.search(request):
        unknowns.append("The request leaves implementation scope or method open; repository evidence must resolve it.")
    if not explicit:
        unknowns.append("Acceptance checks are not explicit and must be derived from repository tests and observable behavior.")
    targets = tuple(dict.fromkeys(_TARGET.findall(request)))
    return IntentContract(
        original_request=request,
        original_request_hash=hashlib.sha256(request.encode("utf-8")).hexdigest(),
        objective=objective,
        acceptance_criteria=criteria,
        constraints=("Preserve behavior outside the accepted objective.",),
        non_goals=("Unrequested production operations or external side effects.",),
        authorization_boundary="Modify repository files required by the accepted objective; external writes require separate authorization.",
        assumptions=(),
        unknowns=tuple(unknowns),
        risk_signals=risk_signals,
        target_artifacts=targets,
    )


def _is_list_item(line: str) -> bool:
    return bool(re.match(r"^(?:[-*]|\d+[.)])\s+", line))


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line).strip()


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
