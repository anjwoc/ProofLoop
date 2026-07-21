from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Enums as frozen sets (no dependency)
# ---------------------------------------------------------------------------

DIMENSIONS = frozenset({
    "MODEL_SELECTION", "MODEL_IDENTITY", "REASONING_SETTING",
    "ACCESS_POLICY", "ROUTING_GRAIN", "TRANSPORT",
})

EVIDENCE_STATES = frozenset({
    "DECLARED", "AVAILABLE", "ACKNOWLEDGED", "OBSERVED",
    "ATTESTATION_CANDIDATE",
})

FORBIDDEN_STATES = frozenset({"ATTESTED", "CERTIFIED", "PROVIDER_SIGNED", "VERIFIED_ATTESTATION"})

SCOPES = frozenset({"RUNTIME", "SESSION", "INVOCATION", "ROLE"})

SOURCE_KINDS = frozenset({
    "DECLARATION", "PROBE", "CORE_REQUEST", "HOST_ACK",
    "HOST_EVENT", "ACP_SESSION_CONFIG",
})

ACK_DISPOSITIONS = frozenset({"ACCEPTED", "SUBSTITUTED", "REJECTED", "UNSUPPORTED"})

# ---------------------------------------------------------------------------
# Record schema fields
# ---------------------------------------------------------------------------

_RECORD_REQUIRED = {"schemaVersion", "recordType", "recordId", "subject", "dimension", "scope", "value", "state", "source"}
_RECORD_ALLOWED = _RECORD_REQUIRED | {"recordSha256"}
_SUBJECT_REQUIRED = {"runtime"}
_SUBJECT_ALLOWED = _SUBJECT_REQUIRED | {"runId", "sessionId", "invocationId", "role", "runtimeVersion"}
_SOURCE_REQUIRED = {"kind"}
_SOURCE_ALLOWED = _SOURCE_REQUIRED | {"artifactSha256", "jsonPointer", "eventType", "parserId", "parserVersion", "ackDisposition"}

# ---------------------------------------------------------------------------
# Stable reason codes
# ---------------------------------------------------------------------------

RECORD_DIGEST_MISMATCH = "RECORD_DIGEST_MISMATCH"
RECORD_UNKNOWN_FIELD = "RECORD_UNKNOWN_FIELD"
RECORD_FORBIDDEN_SOURCE = "RECORD_FORBIDDEN_SOURCE"
RECORD_DUPLICATE_ID = "RECORD_DUPLICATE_ID"
SOURCE_BINDING_INCOMPLETE = "SOURCE_BINDING_INCOMPLETE"
MODEL_ACK_IDENTITY_INSUFFICIENT = "MODEL_ACK_IDENTITY_INSUFFICIENT"
MODEL_HOST_REPORT_UNAUTHENTICATED = "MODEL_HOST_REPORT_UNAUTHENTICATED"
MODEL_VALUE_MISMATCH = "MODEL_VALUE_MISMATCH"
OPAQUE_VALUE_RUNTIME_MISMATCH = "OPAQUE_VALUE_RUNTIME_MISMATCH"
REQUIRED_EVIDENCE_MISSING = "REQUIRED_EVIDENCE_MISSING"
FALLBACK_NOT_ELIGIBLE = "FALLBACK_NOT_ELIGIBLE"
EXPLICIT_FALLBACK_SELECTED = "EXPLICIT_FALLBACK_SELECTED"
CERTIFICATION_NOT_EVALUATED = "CERTIFICATION_NOT_EVALUATED"

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class ValidatedRecordSet(NamedTuple):
    """Immutable set of validated capability records."""
    records: tuple[dict[str, Any], ...]
    reasons: tuple[str, ...]  # empty if all valid


class CapabilityEvaluation(NamedTuple):
    """Immutable per-dimension evaluation result with 6 independent axes."""
    validation: str  # VALID | REJECTED
    support: str  # SUPPORTED | UNSUPPORTED | UNKNOWN
    value_relation: str  # MATCH | SUBSTITUTED | CONFLICT | UNKNOWN
    claim_verdict: str  # SATISFIED | UNPROVEN | CONTRADICTED
    execution_disposition: str  # ALLOW | DOWNGRADE | BLOCK
    certification: str  # always NOT_EVALUATED
    reason_codes: tuple[str, ...]  # stable sorted


class CapabilityValidationError(ValueError):
    """Raised for fatal programming errors in validator usage."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_records(
    records: Sequence[Mapping[str, Any]],
) -> ValidatedRecordSet:
    """Validate a sequence of capability evidence records.

    Returns a ValidatedRecordSet with validated records and any rejection
    reason codes. Malformed records do not flow into evaluation.
    """
    if not isinstance(records, Sequence):
        raise CapabilityValidationError("records must be a sequence")

    reasons: list[str] = []
    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for record in records:
        record_reasons = _validate_record(record, seen_ids)
        reasons.extend(record_reasons)
        if not record_reasons:
            validated.append(copy.deepcopy(dict(record)))

    return ValidatedRecordSet(
        records=tuple(validated),
        reasons=tuple(sorted(set(reasons))),
    )


def evaluate_capability(
    record_set: ValidatedRecordSet,
    claim: Mapping[str, Any],
    fallback: Mapping[str, Any] | None = None,
) -> CapabilityEvaluation:
    """Evaluate a capability claim against validated records.

    Returns a CapabilityEvaluation with 6 independent axes.
    certification is always NOT_EVALUATED in S1.
    """
    reasons: list[str] = []
    reasons.append(CERTIFICATION_NOT_EVALUATED)

    # Validate claim structure
    if not isinstance(claim, Mapping):
        raise CapabilityValidationError("claim must be a mapping")

    claim_type = claim.get("claimType")
    dimension = claim.get("dimension")
    required_state = claim.get("requiredState")
    requested_value = claim.get("requestedValue")
    on_unproven = claim.get("onUnproven", "BLOCK")

    if not isinstance(claim_type, str) or not claim_type:
        return _rejected_evaluation(reasons + [REQUIRED_EVIDENCE_MISSING])
    if dimension not in DIMENSIONS:
        return _rejected_evaluation(reasons + [REQUIRED_EVIDENCE_MISSING])

    # Find matching records for this dimension
    matching = [
        r for r in record_set.records
        if r["dimension"] == dimension
    ]

    if not matching:
        return _missing_evidence_evaluation(on_unproven, fallback, reasons)

    # Separate by state
    ack_records = [r for r in matching if r["state"] == "ACKNOWLEDGED"]
    observed_records = [r for r in matching if r["state"] == "OBSERVED"]

    # Determine support
    declared_records = [r for r in matching if r["state"] in ("DECLARED", "AVAILABLE")]
    support = "UNKNOWN"
    if declared_records or ack_records or observed_records:
        # Check if any ack says UNSUPPORTED
        unsupported_acks = [r for r in ack_records if r["source"].get("ackDisposition") == "UNSUPPORTED"]
        if unsupported_acks:
            support = "UNSUPPORTED"
        else:
            support = "SUPPORTED"

    # Determine value relation
    value_relation = "UNKNOWN"
    if requested_value is not None and observed_records:
        observed_values = [r["value"] for r in observed_records]
        if any(v == requested_value for v in observed_values):
            value_relation = "MATCH"
        else:
            value_relation = "CONFLICT"
            reasons.append(MODEL_VALUE_MISMATCH)
    elif requested_value is not None and ack_records:
        for ack in ack_records:
            disp = ack["source"].get("ackDisposition")
            if disp == "ACCEPTED" and ack["value"] == requested_value:
                value_relation = "MATCH"
            elif disp == "SUBSTITUTED":
                value_relation = "SUBSTITUTED"
            elif disp == "REJECTED":
                value_relation = "CONFLICT"

    # Evaluate claim based on type
    if claim_type == "HOST_REPORTED_MODEL_MATCH":
        return _evaluate_host_reported_match(
            dimension, requested_value, observed_records, ack_records,
            value_relation, support, on_unproven, fallback, reasons,
        )
    elif claim_type == "AUTHENTICATED_MODEL_IDENTITY":
        return _evaluate_authenticated_identity(
            dimension, observed_records, value_relation, support,
            on_unproven, fallback, reasons,
        )
    else:
        # Generic claim evaluation
        return _evaluate_generic_claim(
            dimension, required_state, requested_value, matching,
            value_relation, support, on_unproven, fallback, reasons,
        )


# ---------------------------------------------------------------------------
# Claim evaluators
# ---------------------------------------------------------------------------

def _evaluate_host_reported_match(
    dimension: str,
    requested_value: Any,
    observed_records: list[dict[str, Any]],
    ack_records: list[dict[str, Any]],
    value_relation: str,
    support: str,
    on_unproven: str,
    fallback: Mapping[str, Any] | None,
    reasons: list[str],
) -> CapabilityEvaluation:
    """HOST_REPORTED_MODEL_MATCH: satisfied if matching HOST_EVENT observation."""

    # Need at least one HOST_EVENT observation matching the requested value
    host_observations = [
        r for r in observed_records
        if r["source"]["kind"] == "HOST_EVENT"
    ]

    if not host_observations:
        # Only ack is not enough for this claim
        if ack_records:
            reasons.append(MODEL_ACK_IDENTITY_INSUFFICIENT)
        return _missing_evidence_evaluation(on_unproven, fallback, reasons)

    # Check if any observation matches
    if requested_value is not None:
        matches = [r for r in host_observations if r["value"] == requested_value]
        if matches:
            reasons.append(MODEL_HOST_REPORT_UNAUTHENTICATED)
            return CapabilityEvaluation(
                validation="VALID",
                support=support,
                value_relation="MATCH",
                claim_verdict="SATISFIED",
                execution_disposition="ALLOW",
                certification="NOT_EVALUATED",
                reason_codes=tuple(sorted(set(reasons))),
            )
        else:
            reasons.append(MODEL_VALUE_MISMATCH)
            return CapabilityEvaluation(
                validation="VALID",
                support=support,
                value_relation="CONFLICT",
                claim_verdict="CONTRADICTED",
                execution_disposition="BLOCK",
                certification="NOT_EVALUATED",
                reason_codes=tuple(sorted(set(reasons))),
            )

    # No requested value, just check observation exists
    reasons.append(MODEL_HOST_REPORT_UNAUTHENTICATED)
    return CapabilityEvaluation(
        validation="VALID",
        support=support,
        value_relation=value_relation,
        claim_verdict="SATISFIED",
        execution_disposition="ALLOW",
        certification="NOT_EVALUATED",
        reason_codes=tuple(sorted(set(reasons))),
    )


def _evaluate_authenticated_identity(
    dimension: str,
    observed_records: list[dict[str, Any]],
    value_relation: str,
    support: str,
    on_unproven: str,
    fallback: Mapping[str, Any] | None,
    reasons: list[str],
) -> CapabilityEvaluation:
    """AUTHENTICATED_MODEL_IDENTITY: always UNPROVEN in S1 (no attestation)."""
    reasons.append(REQUIRED_EVIDENCE_MISSING)

    disposition = on_unproven if on_unproven in ("BLOCK", "DOWNGRADE") else "BLOCK"
    if disposition == "DOWNGRADE" and fallback is not None:
        reasons.append(EXPLICIT_FALLBACK_SELECTED)
    elif disposition == "DOWNGRADE" and fallback is None:
        disposition = "BLOCK"
        reasons.append(FALLBACK_NOT_ELIGIBLE)

    return CapabilityEvaluation(
        validation="VALID",
        support=support,
        value_relation=value_relation,
        claim_verdict="UNPROVEN",
        execution_disposition=disposition,
        certification="NOT_EVALUATED",
        reason_codes=tuple(sorted(set(reasons))),
    )


def _evaluate_generic_claim(
    dimension: str,
    required_state: str | None,
    requested_value: Any,
    matching: list[dict[str, Any]],
    value_relation: str,
    support: str,
    on_unproven: str,
    fallback: Mapping[str, Any] | None,
    reasons: list[str],
) -> CapabilityEvaluation:
    """Generic claim: check if required evidence state is met."""

    if required_state and required_state in FORBIDDEN_STATES:
        reasons.append(REQUIRED_EVIDENCE_MISSING)
        return _rejected_evaluation(reasons)

    if not required_state:
        # Default: need at least OBSERVED
        required_state = "OBSERVED"

    state_hierarchy = ["DECLARED", "AVAILABLE", "ACKNOWLEDGED", "OBSERVED", "ATTESTATION_CANDIDATE"]

    # Find records at or above required state
    try:
        req_idx = state_hierarchy.index(required_state)
    except ValueError:
        reasons.append(REQUIRED_EVIDENCE_MISSING)
        return _missing_evidence_evaluation(on_unproven, fallback, reasons)

    qualifying = [
        r for r in matching
        if r["state"] in state_hierarchy[req_idx:]
    ]

    if not qualifying:
        return _missing_evidence_evaluation(on_unproven, fallback, reasons)

    # Check value if requested
    if requested_value is not None:
        value_matches = [r for r in qualifying if r["value"] == requested_value]
        if value_matches:
            return CapabilityEvaluation(
                validation="VALID", support=support, value_relation="MATCH",
                claim_verdict="SATISFIED", execution_disposition="ALLOW",
                certification="NOT_EVALUATED",
                reason_codes=tuple(sorted(set(reasons))),
            )
        # Check for cross-runtime comparison
        runtimes = {r["subject"]["runtime"] for r in qualifying}
        if len(runtimes) > 1:
            reasons.append(OPAQUE_VALUE_RUNTIME_MISMATCH)
            return CapabilityEvaluation(
                validation="VALID", support=support, value_relation="UNKNOWN",
                claim_verdict="UNPROVEN", execution_disposition="BLOCK",
                certification="NOT_EVALUATED",
                reason_codes=tuple(sorted(set(reasons))),
            )

        reasons.append(MODEL_VALUE_MISMATCH)
        return CapabilityEvaluation(
            validation="VALID", support=support, value_relation="CONFLICT",
            claim_verdict="CONTRADICTED", execution_disposition="BLOCK",
            certification="NOT_EVALUATED",
            reason_codes=tuple(sorted(set(reasons))),
        )

    return CapabilityEvaluation(
        validation="VALID", support=support, value_relation=value_relation,
        claim_verdict="SATISFIED", execution_disposition="ALLOW",
        certification="NOT_EVALUATED",
        reason_codes=tuple(sorted(set(reasons))),
    )


# ---------------------------------------------------------------------------
# Record validation
# ---------------------------------------------------------------------------

def _validate_record(
    record: Mapping[str, Any],
    seen_ids: set[str],
) -> list[str]:
    """Validate a single capability record. Returns list of reason codes."""
    reasons: list[str] = []

    if not isinstance(record, Mapping):
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons

    keys = set(record.keys())

    # Check required fields
    if not _RECORD_REQUIRED.issubset(keys):
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons

    # Check no unknown fields
    if keys - _RECORD_ALLOWED:
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons

    # Schema version
    if record.get("schemaVersion") != SCHEMA_VERSION:
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons

    # State validation
    state = record.get("state")
    if state in FORBIDDEN_STATES:
        reasons.append(RECORD_FORBIDDEN_SOURCE)
        return reasons
    if state not in EVIDENCE_STATES:
        reasons.append(RECORD_FORBIDDEN_SOURCE)
        return reasons

    # Dimension
    if record.get("dimension") not in DIMENSIONS:
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons

    # Scope
    if record.get("scope") not in SCOPES:
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons

    # Record ID
    record_id = record.get("recordId")
    if not isinstance(record_id, str) or not record_id:
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons
    if record_id in seen_ids:
        reasons.append(RECORD_DUPLICATE_ID)
        return reasons
    seen_ids.add(record_id)

    # Subject validation
    subject = record.get("subject")
    if not isinstance(subject, Mapping):
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons
    subj_keys = set(subject.keys())
    if not _SUBJECT_REQUIRED.issubset(subj_keys):
        reasons.append(SOURCE_BINDING_INCOMPLETE)
        return reasons
    if subj_keys - _SUBJECT_ALLOWED:
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons
    if not isinstance(subject.get("runtime"), str) or not subject["runtime"]:
        reasons.append(SOURCE_BINDING_INCOMPLETE)
        return reasons

    # Source validation
    source = record.get("source")
    if not isinstance(source, Mapping):
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons
    src_keys = set(source.keys())
    if not _SOURCE_REQUIRED.issubset(src_keys):
        reasons.append(SOURCE_BINDING_INCOMPLETE)
        return reasons
    if src_keys - _SOURCE_ALLOWED:
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons
    if source.get("kind") not in SOURCE_KINDS:
        reasons.append(RECORD_FORBIDDEN_SOURCE)
        return reasons

    # Digest validation (if provided)
    if "recordSha256" in record:
        expected = record["recordSha256"]
        computed = _compute_record_digest(record)
        if expected != computed:
            reasons.append(RECORD_DIGEST_MISMATCH)
            return reasons

    # Value must be present and non-null
    if record.get("value") is None:
        reasons.append(RECORD_UNKNOWN_FIELD)
        return reasons

    return reasons


def _compute_record_digest(record: Mapping[str, Any]) -> str:
    """Compute canonical SHA-256 digest for a record, excluding self-hash."""
    payload = copy.deepcopy(dict(record))
    payload.pop("recordSha256", None)
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _missing_evidence_evaluation(
    on_unproven: str,
    fallback: Mapping[str, Any] | None,
    reasons: list[str],
) -> CapabilityEvaluation:
    """Handle missing required evidence."""
    if REQUIRED_EVIDENCE_MISSING not in reasons:
        reasons.append(REQUIRED_EVIDENCE_MISSING)

    disposition = on_unproven if on_unproven in ("BLOCK", "DOWNGRADE") else "BLOCK"
    if disposition == "DOWNGRADE":
        if fallback is not None:
            reasons.append(EXPLICIT_FALLBACK_SELECTED)
        else:
            disposition = "BLOCK"
            reasons.append(FALLBACK_NOT_ELIGIBLE)

    return CapabilityEvaluation(
        validation="VALID",
        support="UNKNOWN",
        value_relation="UNKNOWN",
        claim_verdict="UNPROVEN",
        execution_disposition=disposition,
        certification="NOT_EVALUATED",
        reason_codes=tuple(sorted(set(reasons))),
    )


def _rejected_evaluation(reasons: list[str]) -> CapabilityEvaluation:
    return CapabilityEvaluation(
        validation="REJECTED",
        support="UNKNOWN",
        value_relation="UNKNOWN",
        claim_verdict="UNPROVEN",
        execution_disposition="BLOCK",
        certification="NOT_EVALUATED",
        reason_codes=tuple(sorted(set(reasons))),
    )
