from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proofloop_core.io import write_json
from proofloop_core.trace import summarize_trace
from proofloop_core.truth import build_truth_report


def write_core_evidence(root: Path) -> None:
    write_json(root / "checks" / "checks.json", {"verdict": "PASS"})
    write_json(root / "diff-guard.json", {"verdict": "PASS", "violations": [], "metrics": {}, "changeBudget": {}, "simplicityPlan": {}})
    write_json(root / "review.json", {"verdict": "APPROVED", "simplicityVerdict": "MINIMAL", "deletionCandidates": []})
    write_json(root / "claims.json", {
        "schemaVersion": "1.0",
        "claims": [
            {"id": "checks", "category": "CHECK_RESULT", "kind": "FACT", "statement": "Required checks passed.", "evidence": [{"artifact": "checks/checks.json", "jsonPointer": "/verdict", "equals": "PASS"}]},
            {"id": "scope", "category": "CHANGE_SCOPE", "kind": "FACT", "statement": "The diff guard passed.", "evidence": [{"artifact": "diff-guard.json", "jsonPointer": "/verdict", "equals": "PASS"}]},
            {"id": "review", "category": "REVIEW_RESULT", "kind": "FACT", "statement": "The independent review approved the change.", "evidence": [{"artifact": "review.json", "jsonPointer": "/verdict", "equals": "APPROVED"}]},
            {"id": "minimal", "category": "SIMPLICITY", "kind": "FACT", "statement": "The reviewer found the implementation minimal.", "evidence": [{"artifact": "review.json", "jsonPointer": "/simplicityVerdict", "equals": "MINIMAL"}]},
        ],
    })


class TruthGateTest(unittest.TestCase):
    def test_missing_trace_is_unproven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_core_evidence(root)
            result = build_truth_report(root)
            self.assertEqual("UNPROVEN", result["verdict"])
            self.assertIn("MODEL_TRACE_MISSING", result["unproven"])

    def test_observed_distinct_models_can_be_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_core_evidence(root)
            trace = root / "model-trace.jsonl"
            trace.write_text("\n".join([
                json.dumps({"role": "planner_deep", "observedModel": "opus"}),
                json.dumps({"role": "implementer_fast", "observedModel": "haiku"}),
                json.dumps({"role": "reviewer_deep", "observedModel": "fable"})
            ]) + "\n", encoding="utf-8")
            write_json(root / "model-trace-summary.json", summarize_trace(trace))
            claims = json.loads((root / "claims.json").read_text(encoding="utf-8"))
            claims["claims"].append({
                "id": "routing",
                "category": "MODEL_ROUTING",
                "kind": "FACT",
                "statement": "Cross-model routing was observed.",
                "evidence": [{"artifact": "model-trace-summary.json", "jsonPointer": "/routingObserved", "equals": True}],
            })
            write_json(root / "claims.json", claims)
            result = build_truth_report(root)
            self.assertEqual("PROVEN", result["verdict"])

    def test_open_current_proof_obligation_prevents_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_core_evidence(root)
            write_json(root / "intent-contract.json", {"schemaVersion": "1.0"})
            write_json(
                root / "proof-graph.json",
                {
                    "schemaVersion": "1.0",
                    "obligations": [
                        {"id": "AC-001", "status": "OPEN", "revision": 1, "requiredAuthority": "DETERMINISTIC_CHECK"}
                    ],
                },
            )
            write_json(
                root / "model-trace-summary.json",
                {"routingClaimed": False, "routingObserved": False},
            )

            result = build_truth_report(root)

            self.assertEqual("FAILED", result["verdict"])
            self.assertIn("PROOF_OBLIGATIONS_OPEN:AC-001", result["blockers"])

    def test_same_model_is_not_cross_model_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            trace.write_text("\n".join([
                json.dumps({"role": "planner_deep", "observedModel": "gemini-pro"}),
                json.dumps({"role": "implementer_fast", "observedModel": "gemini-pro"}),
                json.dumps({"role": "reviewer_deep", "observedModel": "gemini-pro"})
            ]) + "\n", encoding="utf-8")
            summary = summarize_trace(trace)
            self.assertFalse(summary["routingObserved"])

    def test_acp_session_configuration_is_strong_model_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            trace.write_text(
                "\n".join(
                    json.dumps(
                        {
                            "role": role,
                            "observedModel": model,
                            "modelEvidence": "ACP_SESSION_CONFIG",
                        }
                    )
                    for role, model in (
                        ("planner_deep", "opus"),
                        ("implementer_fast", "haiku"),
                        ("reviewer_deep", "fable"),
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            summary = summarize_trace(trace)
            self.assertTrue(summary["routingObserved"])
            self.assertEqual([], summary["weakEvidenceRoles"])


if __name__ == "__main__":
    unittest.main()
