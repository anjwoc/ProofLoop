from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from proofloop_core.engine.intent_gate import IntentGateResult

_RISK_PATTERNS = {
    "auth": re.compile(r"\b(auth|authentication|authorization|permission|login)\b|인증|인가|권한|로그인", re.I),
    "money": re.compile(r"\b(payment|billing|money|invoice)\b|결제|과금|금전", re.I),
    "data": re.compile(r"\b(migration|schema|data loss|production)\b|마이그레이션|스키마|데이터 손실|운영", re.I),
    "security": re.compile(r"\b(security|secret|credential|encryption)\b|보안|비밀|자격 증명|암호화", re.I),
}
_UNCERTAINTY = re.compile(r"\b(appropriate|somehow|as needed|if needed|unknown|unclear|maybe)\b|적당히|알아서|필요하면|불명확|모르", re.I)
_TARGET = re.compile(r"(?<![\w/.-])([\w.-]+(?:/[\w.-]+)+|[\w.-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|md|json|ya?ml))(?![\w/.-])")
_DIRECTORY_TARGET = re.compile(r"(?<![\w/.-])([A-Za-z0-9_.-]+)(?:이란|이라는|라는)?\s*(?:디렉토리|폴더)")
_CONSTRAINT = re.compile(
    r"\b(?:do not|don't|must not|without|keep|preserve|unchanged|forbid|prohibit|no new)\b"
    r"|하지\s*않|하지마|금지|변경하지|유지|추가하지|없애지|삭제하지|성공.*말하지|주장하지",
    re.I,
)
_NON_GOAL = re.compile(r"\b(?:out of scope|non-goal|not required|do not implement)\b|범위\s*밖|비목표|구현하지\s*않", re.I)
_VERIFICATION = re.compile(r"\b(?:test|verify|check|validate|assert|proof)\b|테스트|검증|점검|증명|실행", re.I)
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|(?<=다\.)\s+")


@dataclass(frozen=True)
class SourceRef:
    line: int
    start: int
    end: int
    text_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "start": self.start, "end": self.end, "textSha256": self.text_sha256}


@dataclass(frozen=True)
class AcceptanceCriterion:
    criterion_id: str
    statement: str
    source_refs: tuple[SourceRef, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"id": self.criterion_id, "statement": self.statement}
        if self.source_refs:
            value["sourceRefs"] = [item.to_dict() for item in self.source_refs]
        return value


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
    source_refs: dict[str, tuple[SourceRef, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "1.1",
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
            "sourceRefs": {pointer: [item.to_dict() for item in refs] for pointer, refs in sorted(self.source_refs.items())},
        }


@dataclass(frozen=True)
class _Clause:
    text: str
    ref: SourceRef
    listed: bool


def _clauses(request: str) -> list[_Clause]:
    clauses: list[_Clause] = []
    offset = 0
    for line_number, raw_line in enumerate(request.splitlines(keepends=True), start=1):
        content = raw_line.rstrip("\r\n")
        leading = len(content) - len(content.lstrip())
        stripped = content.strip()
        if not stripped:
            offset += len(raw_line)
            continue
        listed = _is_list_item(stripped)
        normalized = _strip_list_marker(stripped)
        segments = [normalized] if listed else [item.strip() for item in _SENTENCE_BOUNDARY.split(normalized) if item.strip()]
        search_from = 0
        for segment in segments:
            relative = content.find(segment, search_from)
            if relative < 0:
                relative = leading
            start = offset + relative
            end = start + len(segment)
            clauses.append(_Clause(
                text=segment,
                ref=SourceRef(
                    line=line_number,
                    start=start,
                    end=end,
                    text_sha256=hashlib.sha256(segment.encode("utf-8")).hexdigest(),
                ),
                listed=listed,
            ))
            search_from = max(relative + len(segment), search_from)
        offset += len(raw_line)
    return clauses


def compile_intent(request: str, intent_gate_result: IntentGateResult | None = None) -> IntentContract:
    if not request.strip():
        raise ValueError("request must be non-empty")
    clauses = _clauses(request)
    if not clauses:
        raise ValueError("request must contain semantic content")

    objective_clause = next(
        (item for item in clauses if not _CONSTRAINT.search(item.text) and not _NON_GOAL.search(item.text)),
        clauses[0],
    )
    objective = objective_clause.text
    criterion_clauses: list[_Clause] = [objective_clause]
    constraints: list[_Clause] = []
    non_goals: list[_Clause] = []
    for clause in clauses:
        if clause is objective_clause:
            continue
        if _NON_GOAL.search(clause.text):
            non_goals.append(clause)
            if clause.listed:
                criterion_clauses.append(clause)
            continue
        if _CONSTRAINT.search(clause.text):
            constraints.append(clause)
            # A numbered/listed negative requirement describes observable
            # success as well as a boundary. Preserve it in both projections.
            if clause.listed or _VERIFICATION.search(clause.text) or re.search(r"성공|claim|주장", clause.text, re.I):
                criterion_clauses.append(clause)
            continue
        if clause.listed or _VERIFICATION.search(clause.text):
            criterion_clauses.append(clause)

    criterion_clauses = _dedupe_clauses(criterion_clauses)
    criteria = tuple(
        AcceptanceCriterion(f"AC-{index:03d}", item.text, (item.ref,))
        for index, item in enumerate(criterion_clauses, start=1)
    )

    if intent_gate_result is not None:
        risk_signals = tuple(intent_gate_result.signals)
        is_uncertain = intent_gate_result.clarity.value == "owner_decision_required"
    else:
        risk_signals = tuple(name for name, pattern in _RISK_PATTERNS.items() if pattern.search(request))
        is_uncertain = bool(_UNCERTAINTY.search(request))

    unknowns: list[str] = []
    if is_uncertain:
        unknowns.append("The request leaves implementation scope or method open; repository evidence must resolve it.")
    target_candidates = [
        *(value.rstrip(".,;:!?") for value in _TARGET.findall(request)),
        *(f"{name}/**" for name in _DIRECTORY_TARGET.findall(request)),
    ]
    targets = tuple(dict.fromkeys(value for value in target_candidates if value))
    if not targets:
        unknowns.append("Repository-specific target paths and symbols must be resolved from grounding evidence.")

    explicit_constraints = _dedupe_clauses(constraints)
    explicit_non_goals = _dedupe_clauses(non_goals)
    constraint_text = [item.text for item in explicit_constraints]
    if "Preserve behavior outside the accepted objective." not in constraint_text:
        constraint_text.append("Preserve behavior outside the accepted objective.")
    non_goal_text = [item.text for item in explicit_non_goals]
    if "Unrequested production operations or external side effects." not in non_goal_text:
        non_goal_text.append("Unrequested production operations or external side effects.")

    source_refs: dict[str, tuple[SourceRef, ...]] = {"/objective": (objective_clause.ref,)}
    for index, criterion in enumerate(criteria):
        source_refs[f"/acceptanceCriteria/{index}"] = criterion.source_refs
    for index, item in enumerate(explicit_constraints):
        source_refs[f"/constraints/{index}"] = (item.ref,)
    for index, item in enumerate(explicit_non_goals):
        source_refs[f"/nonGoals/{index}"] = (item.ref,)

    return IntentContract(
        original_request=request,
        original_request_hash=hashlib.sha256(request.encode("utf-8")).hexdigest(),
        objective=objective,
        acceptance_criteria=criteria,
        constraints=tuple(constraint_text),
        non_goals=tuple(non_goal_text),
        authorization_boundary="Modify repository files required by the accepted objective; external writes require separate authorization.",
        assumptions=(),
        unknowns=tuple(unknowns),
        risk_signals=risk_signals,
        target_artifacts=targets,
        source_refs=source_refs,
    )


def _is_list_item(line: str) -> bool:
    return bool(re.match(r"^(?:[-*]|\d+[.)])\s+", line))


def _strip_list_marker(line: str) -> str:
    return re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line).strip()


def _dedupe_clauses(values: list[_Clause]) -> list[_Clause]:
    result: list[_Clause] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.text.split()).casefold()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(value)
    return result


def format_intent_contract(contract: IntentContract) -> str:
    """Format an IntentContract for display only, never as execution authority."""
    parts = [f"**Objective**: {contract.objective}"]
    if contract.acceptance_criteria:
        parts.append("\n**Acceptance Criteria**:")
        for ac in contract.acceptance_criteria:
            parts.append(f"- [{ac.criterion_id}] {ac.statement}")
    if contract.constraints:
        parts.append("\n**Constraints**:")
        for constraint in contract.constraints:
            parts.append(f"- {constraint}")
    if contract.non_goals:
        parts.append("\n**Non-Goals**:")
        for non_goal in contract.non_goals:
            parts.append(f"- {non_goal}")
    if contract.unknowns:
        parts.append("\n**Unknowns / Uncertainties**:")
        for unknown in contract.unknowns:
            parts.append(f"- {unknown}")
    return "\n".join(parts)
