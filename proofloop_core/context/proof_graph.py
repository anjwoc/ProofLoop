from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from proofloop_core.contracts.evidence_policy import ClaimType, EvidenceOrigin, EvidencePolicy

AUTHORITY = {
    "MODEL_CLAIM": 0,
    "MODEL_REVIEW": 1,
    "STATIC_INSPECTION": 2,
    "DIFF_GUARD": 2,
    "DETERMINISTIC_CHECK": 3,
    "EXTERNAL_OBSERVATION": 4,
}

_OBLIGATION_CLAIMS = {
    "PROMPT-CONTRACT": ClaimType.PROMPT_CONTRACT_APPLIED.value,
    "scope-integrity": ClaimType.SCOPE_INTEGRITY.value,
    "SCOPE-INTEGRITY": ClaimType.SCOPE_INTEGRITY.value,
    "simplicity": ClaimType.SIMPLICITY.value,
}


def _origin_for_authority(authority: str) -> str:
    return {
        "DIFF_GUARD": EvidenceOrigin.CORE_DIFF_GUARD.value,
        "MODEL_REVIEW": EvidenceOrigin.PARENT_REVIEW.value,
        "EXTERNAL_OBSERVATION": EvidenceOrigin.PARENT_EXTERNAL_OBSERVATION.value,
    }.get(authority, EvidenceOrigin.CORE_DETERMINISTIC.value)


@dataclass
class Evidence:
    evidence_id: str
    obligation_id: str
    authority: str
    artifact: str
    revision: int
    verdict: str = "PASS"
    evidence_level: str | None = None
    origin: str | None = None
    claim_type: str | None = None
    run_id: str = ""
    invocation_id: str | None = None

    def __post_init__(self) -> None:
        if self.claim_type is None:
            self.claim_type = _OBLIGATION_CLAIMS.get(
                self.obligation_id,
                ClaimType.PRODUCT_BEHAVIOR.value,
            )
        if self.origin is None:
            self.origin = _origin_for_authority(self.authority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.evidence_id,
            "obligationId": self.obligation_id,
            "authority": self.authority,
            "artifact": self.artifact,
            "revision": self.revision,
            "verdict": self.verdict,
            "evidenceLevel": self.evidence_level,
            "origin": self.origin,
            "claimType": self.claim_type,
            "runId": self.run_id,
            "invocationId": self.invocation_id,
        }


@dataclass
class ProofObligation:
    obligation_id: str
    statement: str
    required_authority: str
    claim_type: str | None = None
    required: bool = True
    revision: int = 0
    status: str = "OPEN"
    evidence_ids: list[str] = field(default_factory=list)
    last_reason: str | None = None

    def __post_init__(self) -> None:
        if self.claim_type is None:
            self.claim_type = _OBLIGATION_CLAIMS.get(
                self.obligation_id,
                ClaimType.PRODUCT_BEHAVIOR.value,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.obligation_id,
            "statement": self.statement,
            "requiredAuthority": self.required_authority,
            "claimType": self.claim_type,
            "required": self.required,
            "revision": self.revision,
            "status": self.status,
            "evidenceIds": list(self.evidence_ids),
            "lastReason": self.last_reason,
        }


@dataclass
class ProofGraph:
    obligations: list[ProofObligation]
    evidence: list[Evidence] = field(default_factory=list)
    run_id: str = ""

    @property
    def closure_ratio(self) -> float:
        required = [item for item in self.obligations if item.required]
        if not required:
            return 1.0
        return sum(item.status == "CLOSED" for item in required) / len(required)

    def add_obligation(self, obligation: ProofObligation) -> None:
        if any(item.obligation_id == obligation.obligation_id for item in self.obligations):
            raise ValueError(f"duplicate proof obligation: {obligation.obligation_id}")
        self.obligations.append(obligation)

    def record(self, evidence: Evidence) -> None:
        if evidence.authority not in AUTHORITY:
            raise ValueError(f"unsupported evidence authority: {evidence.authority}")
        obligation = next((item for item in self.obligations if item.obligation_id == evidence.obligation_id), None)
        if obligation is None:
            raise ValueError(f"unknown proof obligation: {evidence.obligation_id}")
        self.evidence.append(evidence)
        obligation.evidence_ids.append(evidence.evidence_id)
        if evidence.revision != obligation.revision:
            obligation.last_reason = "STALE_EVIDENCE"
            return
        if evidence.verdict != "PASS":
            obligation.last_reason = "EVIDENCE_DID_NOT_PASS"
            return
        if evidence.claim_type != obligation.claim_type:
            obligation.last_reason = "EVIDENCE_CLAIM_TYPE_MISMATCH"
            return
        if self.run_id and evidence.run_id != self.run_id:
            obligation.last_reason = "EVIDENCE_RUN_MISMATCH"
            return
        if evidence.origin == EvidenceOrigin.PARENT_HOST_RECEIPT.value and not evidence.invocation_id:
            obligation.last_reason = "HOST_RECEIPT_INVOCATION_MISSING"
            return
        eligibility = EvidencePolicy.can_close(
            claim_type=str(obligation.claim_type),
            origin=str(evidence.origin),
            authority=evidence.authority,
        )
        if not eligibility.allowed:
            obligation.last_reason = eligibility.reason
            return
        obligation.status = "CLOSED"
        obligation.last_reason = None

    def claim_summary(self) -> dict[str, str]:
        summary: dict[str, str] = {}
        for claim in ClaimType:
            relevant = [item for item in self.obligations if item.claim_type == claim.value and item.required]
            if not relevant:
                summary[claim.value] = "NOT_REQUIRED"
            elif all(item.status == "CLOSED" for item in relevant):
                summary[claim.value] = "CLOSED"
            else:
                summary[claim.value] = "OPEN"
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "2.0",
            "runId": self.run_id,
            "closureRatio": self.closure_ratio,
            "claims": self.claim_summary(),
            "obligations": [item.to_dict() for item in self.obligations],
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_intent(cls, criteria: list[dict[str, Any]], *, run_id: str = "") -> "ProofGraph":
        obligations = [
            ProofObligation(
                str(item["id"]),
                str(item["statement"]),
                "DETERMINISTIC_CHECK",
                claim_type=ClaimType.PRODUCT_BEHAVIOR.value,
            )
            for item in criteria
        ]
        obligations.extend((
            ProofObligation(
                "PROMPT-CONTRACT",
                "The user request passed through the active prompt compilation contract.",
                "DETERMINISTIC_CHECK",
                claim_type=ClaimType.PROMPT_CONTRACT_APPLIED.value,
            ),
            ProofObligation(
                "SCOPE-INTEGRITY",
                "Changed files and dependencies comply with the frozen task contract.",
                "DIFF_GUARD",
                claim_type=ClaimType.SCOPE_INTEGRITY.value,
            ),
        ))
        return cls(obligations=obligations, run_id=run_id)
