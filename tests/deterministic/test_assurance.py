from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from proofloop_core.assurance import build_assurance_report
from proofloop_core.io import write_json


def write_artifacts(root: Path, *, simplicity: str = "MINIMAL") -> None:
    write_json(root / "checks" / "checks.json", {"verdict": "PASS"})
    write_json(root / "diff-guard.json", {"verdict": "PASS", "violations": [], "metrics": {"addedLines": 3}, "changeBudget": {"maxAddedLines": 20}, "simplicityPlan": {"selectedRung": "DIRECT_CHANGE"}})
    write_json(root / "review.json", {"verdict": "APPROVED", "simplicityVerdict": simplicity, "deletionCandidates": []})


def supported_claims() -> dict:
    return {
        "schemaVersion": "1.0",
        "claims": [
            {"id": "c1", "category": "CHECK_RESULT", "kind": "FACT", "statement": "Checks passed.", "evidence": [{"artifact": "checks/checks.json", "jsonPointer": "/verdict", "equals": "PASS"}]},
            {"id": "c2", "category": "CHANGE_SCOPE", "kind": "FACT", "statement": "Scope guard passed.", "evidence": [{"artifact": "diff-guard.json", "jsonPointer": "/verdict", "equals": "PASS"}]},
            {"id": "c3", "category": "REVIEW_RESULT", "kind": "FACT", "statement": "Review approved.", "evidence": [{"artifact": "review.json", "jsonPointer": "/verdict", "equals": "APPROVED"}]},
            {"id": "c4", "category": "SIMPLICITY", "kind": "FACT", "statement": "Implementation is minimal.", "evidence": [{"artifact": "review.json", "jsonPointer": "/simplicityVerdict", "equals": "MINIMAL"}]},
        ],
    }


class AssuranceTest(unittest.TestCase):
    def test_supported_claims_and_minimal_review_are_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_artifacts(root)
            write_json(root / "claims.json", supported_claims())
            report = build_assurance_report(root)
            self.assertEqual("PROVEN", report["verdict"])

    def test_contradicted_fact_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_artifacts(root)
            claims = supported_claims()
            claims["claims"][0]["evidence"][0]["equals"] = "FAIL"
            write_json(root / "claims.json", claims)
            report = build_assurance_report(root)
            self.assertEqual("FAILED", report["verdict"])
            self.assertTrue(any("CONTRADICTED" in item for item in report["blocking"]))

    def test_overbuilt_review_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_artifacts(root, simplicity="OVERBUILT")
            write_json(root / "claims.json", supported_claims())
            report = build_assurance_report(root)
            self.assertEqual("FAILED", report["verdict"])
            self.assertIn("SIMPLICITY:REVIEW_FOUND_OVERBUILD", report["blocking"])


if __name__ == "__main__":
    unittest.main()
