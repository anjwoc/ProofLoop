from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EvidenceOrigin(str, Enum):
    CORE_DETERMINISTIC = "CORE_DETERMINISTIC"
    CORE_DIFF_GUARD = "CORE_DIFF_GUARD"
    PARENT_HOST_RECEIPT = "PARENT_HOST_RECEIPT"
    PARENT_EXTERNAL_OBSERVATION = "PARENT_EXTERNAL_OBSERVATION"
    PARENT_REVIEW = "PARENT_REVIEW"
    PROGRAMMATIC = "PROGRAMMATIC"
    TEST_MECHANICS = "TEST_MECHANICS"
    MODEL_OUTPUT = "MODEL_OUTPUT"


class ClaimType(str, Enum):
    PROMPT_CONTRACT_APPLIED = "PROMPT_CONTRACT_APPLIED"
    PRODUCT_BEHAVIOR = "PRODUCT_BEHAVIOR"
    SCOPE_INTEGRITY = "SCOPE_INTEGRITY"
    HOST_EXECUTION = "HOST_EXECUTION"
    MODEL_ROUTING = "MODEL_ROUTING"
    EXTERNAL_OBSERVATION = "EXTERNAL_OBSERVATION"
    SIMPLICITY = "SIMPLICITY"


@dataclass(frozen=True)
class Eligibility:
    allowed: bool
    reason: str


_ALLOWED_ORIGINS: dict[ClaimType, frozenset[EvidenceOrigin]] = {
    ClaimType.PROMPT_CONTRACT_APPLIED: frozenset({EvidenceOrigin.CORE_DETERMINISTIC}),
    ClaimType.PRODUCT_BEHAVIOR: frozenset({EvidenceOrigin.CORE_DETERMINISTIC}),
    ClaimType.SCOPE_INTEGRITY: frozenset({EvidenceOrigin.CORE_DIFF_GUARD, EvidenceOrigin.CORE_DETERMINISTIC}),
    ClaimType.HOST_EXECUTION: frozenset({EvidenceOrigin.PARENT_HOST_RECEIPT}),
    ClaimType.MODEL_ROUTING: frozenset({EvidenceOrigin.PARENT_HOST_RECEIPT}),
    ClaimType.EXTERNAL_OBSERVATION: frozenset({EvidenceOrigin.PARENT_EXTERNAL_OBSERVATION}),
    ClaimType.SIMPLICITY: frozenset({EvidenceOrigin.CORE_DIFF_GUARD, EvidenceOrigin.CORE_DETERMINISTIC, EvidenceOrigin.PARENT_REVIEW}),
}

_AUTHORITY_MINIMUM: dict[ClaimType, frozenset[str]] = {
    ClaimType.PROMPT_CONTRACT_APPLIED: frozenset({"DETERMINISTIC_CHECK"}),
    ClaimType.PRODUCT_BEHAVIOR: frozenset({"DETERMINISTIC_CHECK"}),
    ClaimType.SCOPE_INTEGRITY: frozenset({"DIFF_GUARD", "DETERMINISTIC_CHECK"}),
    ClaimType.HOST_EXECUTION: frozenset({"EXTERNAL_OBSERVATION"}),
    ClaimType.MODEL_ROUTING: frozenset({"EXTERNAL_OBSERVATION"}),
    ClaimType.EXTERNAL_OBSERVATION: frozenset({"EXTERNAL_OBSERVATION"}),
    ClaimType.SIMPLICITY: frozenset({"DIFF_GUARD", "DETERMINISTIC_CHECK", "MODEL_REVIEW"}),
}


class EvidencePolicy:
    @staticmethod
    def can_close(*, claim_type: str, origin: str, authority: str) -> Eligibility:
        try:
            claim = ClaimType(claim_type)
        except ValueError:
            return Eligibility(False, "EVIDENCE_CLAIM_TYPE_UNKNOWN")
        try:
            evidence_origin = EvidenceOrigin(origin)
        except ValueError:
            return Eligibility(False, "EVIDENCE_ORIGIN_UNKNOWN")
        if evidence_origin not in _ALLOWED_ORIGINS[claim]:
            return Eligibility(False, "EVIDENCE_ORIGIN_NOT_ELIGIBLE")
        if authority not in _AUTHORITY_MINIMUM[claim]:
            return Eligibility(False, "EVIDENCE_AUTHORITY_NOT_ELIGIBLE")
        return Eligibility(True, "ELIGIBLE")

    @staticmethod
    def permitted_origins(claim_type: str) -> tuple[str, ...]:
        claim = ClaimType(claim_type)
        return tuple(sorted(item.value for item in _ALLOWED_ORIGINS[claim]))
