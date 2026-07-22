from __future__ import annotations

import copy
import hashlib
import json
import unittest
from typing import Any

from proofloop_core.contracts.capability_contract import (
    CERTIFICATION_NOT_EVALUATED,
    EXPLICIT_FALLBACK_SELECTED,
    FALLBACK_NOT_ELIGIBLE,
    MODEL_ACK_IDENTITY_INSUFFICIENT,
    MODEL_HOST_REPORT_UNAUTHENTICATED,
    MODEL_VALUE_MISMATCH,
    OPAQUE_VALUE_RUNTIME_MISMATCH,
    RECORD_DIGEST_MISMATCH,
    RECORD_DUPLICATE_ID,
    RECORD_FORBIDDEN_SOURCE,
    RECORD_UNKNOWN_FIELD,
    REQUIRED_EVIDENCE_MISSING,
    SOURCE_BINDING_INCOMPLETE,
    evaluate_capability,
    validate_records,
)


def _record(
    *,
    record_id: str = "R-001",
    dimension: str = "MODEL_IDENTITY",
    scope: str = "INVOCATION",
    value: str = "gpt-5.6-terra",
    state: str = "OBSERVED",
    runtime: str = "codex",
    source_kind: str = "HOST_EVENT",
    include_digest: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    """Build a minimal valid capability record."""
    source: dict[str, Any] = {"kind": source_kind}
    if source_kind == "HOST_EVENT":
        source["artifactSha256"] = "a" * 64
        source["jsonPointer"] = "/model"
    if source_kind == "HOST_ACK":
        source["ackDisposition"] = extra.pop("ackDisposition", "ACCEPTED")

    rec: dict[str, Any] = {
        "schemaVersion": "1.0",
        "recordType": "CAPABILITY_OBSERVATION",
        "recordId": record_id,
        "subject": {"runtime": runtime, "invocationId": "inv-001", "role": "implementer_fast"},
        "dimension": dimension,
        "scope": scope,
        "value": value,
        "state": state,
        "source": source,
    }
    rec.update(extra)

    if include_digest:
        payload = copy.deepcopy(rec)
        payload.pop("recordSha256", None)
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        rec["recordSha256"] = hashlib.sha256(encoded).hexdigest()

    return rec


def _claim(
    *,
    claim_type: str = "HOST_REPORTED_MODEL_MATCH",
    dimension: str = "MODEL_IDENTITY",
    requested_value: str | None = "gpt-5.6-terra",
    on_unproven: str = "BLOCK",
    **extra: Any,
) -> dict[str, Any]:
    c: dict[str, Any] = {
        "claimType": claim_type,
        "dimension": dimension,
        "requestedValue": requested_value,
        "onUnproven": on_unproven,
    }
    c.update(extra)
    return c


class CapabilityRecordValidationTest(unittest.TestCase):
    # ------------------------------------------------------------------
    # 1. Record/claim permutation yields byte-equivalent evaluation
    # ------------------------------------------------------------------
    def test_permutation_invariant_evaluation(self) -> None:
        r1 = _record(record_id="R-001", value="gpt-5.6-terra")
        r2 = _record(record_id="R-002", value="gpt-5.6-terra", state="ACKNOWLEDGED",
                      source_kind="HOST_ACK")
        claim = _claim()

        rs_fwd = validate_records([r1, r2])
        rs_rev = validate_records([r2, r1])

        e1 = evaluate_capability(rs_fwd, claim)
        e2 = evaluate_capability(rs_rev, claim)

        self.assertEqual(e1, e2)

    # ------------------------------------------------------------------
    # 2. Declaration/probe/request cannot prove model identity
    # ------------------------------------------------------------------
    def test_declaration_probe_request_no_identity_proof(self) -> None:
        for src_kind, state in [
            ("DECLARATION", "DECLARED"),
            ("PROBE", "AVAILABLE"),
            ("CORE_REQUEST", "DECLARED"),
        ]:
            with self.subTest(source_kind=src_kind):
                rec = _record(state=state, source_kind=src_kind)
                rs = validate_records([rec])
                claim = _claim(claim_type="HOST_REPORTED_MODEL_MATCH")
                result = evaluate_capability(rs, claim)

                self.assertNotEqual(result.claim_verdict, "SATISFIED")

    # ------------------------------------------------------------------
    # 3. ACP exact ack → identity UNPROVEN
    # ------------------------------------------------------------------
    def test_acp_ack_identity_unproven(self) -> None:
        rec = _record(
            state="ACKNOWLEDGED", source_kind="HOST_ACK",
            ackDisposition="ACCEPTED",
        )
        rs = validate_records([rec])
        claim = _claim(claim_type="HOST_REPORTED_MODEL_MATCH")
        result = evaluate_capability(rs, claim)

        self.assertEqual(result.claim_verdict, "UNPROVEN")
        self.assertIn(MODEL_ACK_IDENTITY_INSUFFICIENT, result.reason_codes)

    # ------------------------------------------------------------------
    # 4. Ack substitution → SUBSTITUTED, not copied to observed
    # ------------------------------------------------------------------
    def test_ack_substitution_not_copied(self) -> None:
        rec = _record(
            state="ACKNOWLEDGED", source_kind="HOST_ACK",
            ackDisposition="SUBSTITUTED", value="gpt-4-turbo",
        )
        rs = validate_records([rec])
        claim = _claim(
            claim_type="HOST_REPORTED_MODEL_MATCH",
            requested_value="gpt-5.6-terra",
        )
        result = evaluate_capability(rs, claim)

        self.assertEqual(result.claim_verdict, "UNPROVEN")

    # ------------------------------------------------------------------
    # 5. Host report stays unauthenticated
    # ------------------------------------------------------------------
    def test_host_report_unauthenticated(self) -> None:
        rec = _record(state="OBSERVED", source_kind="HOST_EVENT")
        rs = validate_records([rec])
        claim = _claim(claim_type="HOST_REPORTED_MODEL_MATCH")
        result = evaluate_capability(rs, claim)

        self.assertEqual(result.claim_verdict, "SATISFIED")
        self.assertIn(MODEL_HOST_REPORT_UNAUTHENTICATED, result.reason_codes)

    # ------------------------------------------------------------------
    # 6. Forbidden state/source rejected
    # ------------------------------------------------------------------
    def test_forbidden_state_rejected(self) -> None:
        for forbidden in ("ATTESTED", "CERTIFIED", "PROVIDER_SIGNED", "VERIFIED_ATTESTATION"):
            with self.subTest(state=forbidden):
                rec = _record(state=forbidden)
                rs = validate_records([rec])
                self.assertTrue(len(rs.reasons) > 0)
                self.assertIn(RECORD_FORBIDDEN_SOURCE, rs.reasons)

    # ------------------------------------------------------------------
    # 7. Required missing → BLOCK
    # ------------------------------------------------------------------
    def test_required_missing_blocks(self) -> None:
        rs = validate_records([])
        claim = _claim()
        result = evaluate_capability(rs, claim)

        self.assertEqual(result.claim_verdict, "UNPROVEN")
        self.assertEqual(result.execution_disposition, "BLOCK")
        self.assertIn(REQUIRED_EVIDENCE_MISSING, result.reason_codes)

    # ------------------------------------------------------------------
    # 8. Explicit eligible fallback → DOWNGRADE
    # ------------------------------------------------------------------
    def test_explicit_fallback_downgrade(self) -> None:
        rs = validate_records([])
        claim = _claim(on_unproven="DOWNGRADE")
        fallback = {"runtime": "antigravity", "model": "gemini-3.1-pro"}
        result = evaluate_capability(rs, claim, fallback=fallback)

        self.assertEqual(result.execution_disposition, "DOWNGRADE")
        self.assertIn(EXPLICIT_FALLBACK_SELECTED, result.reason_codes)

    # ------------------------------------------------------------------
    # 9. No fallback → BLOCK even with DOWNGRADE policy
    # ------------------------------------------------------------------
    def test_no_fallback_blocks_despite_downgrade_policy(self) -> None:
        rs = validate_records([])
        claim = _claim(on_unproven="DOWNGRADE")
        result = evaluate_capability(rs, claim, fallback=None)

        self.assertEqual(result.execution_disposition, "BLOCK")
        self.assertIn(FALLBACK_NOT_ELIGIBLE, result.reason_codes)

    # ------------------------------------------------------------------
    # 10. Antigravity session → per-role routing not satisfied
    # ------------------------------------------------------------------
    def test_antigravity_session_not_per_role(self) -> None:
        rec = _record(
            dimension="ROUTING_GRAIN", scope="SESSION",
            value="SESSION_ONLY", state="OBSERVED",
            runtime="antigravity",
        )
        rs = validate_records([rec])
        claim = _claim(
            claim_type="GENERIC",
            dimension="ROUTING_GRAIN",
            requested_value="PER_ROLE",
            requiredState="OBSERVED",
        )
        result = evaluate_capability(rs, claim)

        self.assertNotEqual(result.claim_verdict, "SATISFIED")
        self.assertIn(MODEL_VALUE_MISMATCH, result.reason_codes)

    # ------------------------------------------------------------------
    # 11. Cross-runtime reasoning/access comparison → UNPROVEN
    # ------------------------------------------------------------------
    def test_cross_runtime_reasoning_unproven(self) -> None:
        r1 = _record(
            record_id="R-001", dimension="REASONING_SETTING",
            value="high", runtime="codex",
        )
        r2 = _record(
            record_id="R-002", dimension="REASONING_SETTING",
            value="medium", runtime="claude",
        )
        rs = validate_records([r1, r2])
        claim = _claim(
            claim_type="GENERIC",
            dimension="REASONING_SETTING",
            requested_value="high-equivalent",
            requiredState="OBSERVED",
        )
        result = evaluate_capability(rs, claim)

        self.assertEqual(result.claim_verdict, "UNPROVEN")
        self.assertIn(OPAQUE_VALUE_RUNTIME_MISMATCH, result.reason_codes)

    # ------------------------------------------------------------------
    # 12. Unknown field, malformed subject, duplicate ID, digest mismatch
    # ------------------------------------------------------------------
    def test_unknown_field_rejected(self) -> None:
        rec = _record()
        rec["unknownField"] = "bad"
        rs = validate_records([rec])
        self.assertIn(RECORD_UNKNOWN_FIELD, rs.reasons)

    def test_malformed_subject_rejected(self) -> None:
        rec = _record()
        rec["subject"] = {"noRuntime": True}
        rs = validate_records([rec])
        self.assertTrue(len(rs.reasons) > 0)

    def test_duplicate_id_rejected(self) -> None:
        r1 = _record(record_id="DUP")
        r2 = _record(record_id="DUP")
        rs = validate_records([r1, r2])
        self.assertIn(RECORD_DUPLICATE_ID, rs.reasons)

    def test_digest_mismatch_rejected(self) -> None:
        rec = _record(include_digest=True)
        rec["value"] = "tampered-model"
        rs = validate_records([rec])
        self.assertIn(RECORD_DIGEST_MISMATCH, rs.reasons)

    # ------------------------------------------------------------------
    # 13. CERTIFIED output impossible
    # ------------------------------------------------------------------
    def test_certified_never_output(self) -> None:
        rec = _record()
        rs = validate_records([rec])
        claim = _claim()
        result = evaluate_capability(rs, claim)

        self.assertEqual(result.certification, "NOT_EVALUATED")
        self.assertIn(CERTIFICATION_NOT_EVALUATED, result.reason_codes)

    # ------------------------------------------------------------------
    # 14. AUTHENTICATED_MODEL_IDENTITY → always UNPROVEN in S1
    # ------------------------------------------------------------------
    def test_authenticated_identity_always_unproven(self) -> None:
        rec = _record(state="OBSERVED", source_kind="HOST_EVENT")
        rs = validate_records([rec])
        claim = _claim(claim_type="AUTHENTICATED_MODEL_IDENTITY")
        result = evaluate_capability(rs, claim)

        self.assertEqual(result.claim_verdict, "UNPROVEN")
        self.assertIn(REQUIRED_EVIDENCE_MISSING, result.reason_codes)

    # ------------------------------------------------------------------
    # 15. Stable sorted reason codes
    # ------------------------------------------------------------------
    def test_reason_codes_stable_sorted(self) -> None:
        rec = _record()
        rs = validate_records([rec])
        claim = _claim()
        result = evaluate_capability(rs, claim)

        self.assertEqual(list(result.reason_codes), sorted(result.reason_codes))

    # ------------------------------------------------------------------
    # 16. Unbound source rejected
    # ------------------------------------------------------------------
    def test_unbound_source_rejected(self) -> None:
        rec = _record()
        rec["source"] = {}  # missing 'kind'
        rs = validate_records([rec])
        self.assertIn(SOURCE_BINDING_INCOMPLETE, rs.reasons)

    # ------------------------------------------------------------------
    # 17. Valid record with correct digest passes
    # ------------------------------------------------------------------
    def test_valid_record_with_digest_passes(self) -> None:
        rec = _record(include_digest=True)
        rs = validate_records([rec])
        self.assertEqual(rs.reasons, ())
        self.assertEqual(len(rs.records), 1)

    # ------------------------------------------------------------------
    # 18. HOST_REPORTED with value mismatch → CONTRADICTED
    # ------------------------------------------------------------------
    def test_host_reported_value_mismatch_contradicted(self) -> None:
        rec = _record(value="gpt-4-turbo")
        rs = validate_records([rec])
        claim = _claim(
            claim_type="HOST_REPORTED_MODEL_MATCH",
            requested_value="gpt-5.6-terra",
        )
        result = evaluate_capability(rs, claim)

        self.assertEqual(result.claim_verdict, "CONTRADICTED")
        self.assertIn(MODEL_VALUE_MISMATCH, result.reason_codes)


if __name__ == "__main__":
    unittest.main()
