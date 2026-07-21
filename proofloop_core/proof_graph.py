from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


AUTHORITY = {
    "MODEL_CLAIM": 0,
    "MODEL_REVIEW": 1,
    "STATIC_INSPECTION": 2,
    "DIFF_GUARD": 2,
    "DETERMINISTIC_CHECK": 3,
    "EXTERNAL_OBSERVATION": 4,
}


@dataclass
class Evidence:
    evidence_id: str
    obligation_id: str
    authority: str
    artifact: str
    revision: int
    verdict: str = "PASS"
    evidence_level: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.evidence_id,
            "obligationId": self.obligation_id,
            "authority": self.authority,
            "artifact": self.artifact,
            "revision": self.revision,
            "verdict": self.verdict,
        }


@dataclass
class ProofObligation:
    obligation_id: str
    statement: str
    required_authority: str
    revision: int = 0
    status: str = "OPEN"
    evidence_ids: list[str] = field(default_factory=list)
    last_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.obligation_id,
            "statement": self.statement,
            "requiredAuthority": self.required_authority,
            "revision": self.revision,
            "status": self.status,
            "evidenceIds": list(self.evidence_ids),
            "lastReason": self.last_reason,
        }


@dataclass
class ProofGraph:
    obligations: list[ProofObligation]
    evidence: list[Evidence] = field(default_factory=list)

    @property
    def closure_ratio(self) -> float:
        if not self.obligations:
            return 1.0
        return sum(item.status == "CLOSED" for item in self.obligations) / len(self.obligations)

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

        eff_authority = evidence.authority
        if obligation.required_authority == "EXTERNAL_OBSERVATION":
            if evidence.evidence_level not in {"E-01", "E-02", "E-03", "E-04", "E-05", "E-06"}:
                eff_authority = "STATIC_INSPECTION"

        if AUTHORITY[eff_authority] < AUTHORITY[obligation.required_authority]:
            obligation.last_reason = "INSUFFICIENT_AUTHORITY"
            return
        obligation.status = "CLOSED"
        obligation.last_reason = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0",
            "closureRatio": self.closure_ratio,
            "obligations": [item.to_dict() for item in self.obligations],
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @classmethod
    def from_intent(cls, criteria: list[dict[str, Any]]) -> "ProofGraph":
        return cls(
            obligations=[
                ProofObligation(str(item["id"]), str(item["statement"]), "DETERMINISTIC_CHECK")
                for item in criteria
            ]
        )
