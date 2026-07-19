from __future__ import annotations

import unittest

from proofloop_core.proof_graph import Evidence, ProofGraph, ProofObligation


class ProofGraphTest(unittest.TestCase):
    def test_model_claim_cannot_close_deterministic_obligation(self) -> None:
        graph = ProofGraph(
            obligations=[ProofObligation("AC-001", "tests pass", required_authority="DETERMINISTIC_CHECK")]
        )

        graph.record(Evidence("ev-1", "AC-001", "MODEL_CLAIM", "review.json", revision=0))

        self.assertEqual("OPEN", graph.obligations[0].status)
        self.assertEqual("INSUFFICIENT_AUTHORITY", graph.obligations[0].last_reason)

    def test_authoritative_evidence_closes_matching_current_obligation(self) -> None:
        graph = ProofGraph(
            obligations=[ProofObligation("AC-001", "tests pass", required_authority="DETERMINISTIC_CHECK")]
        )

        graph.record(Evidence("ev-1", "AC-001", "DETERMINISTIC_CHECK", "checks.json", revision=0))

        self.assertEqual("CLOSED", graph.obligations[0].status)
        self.assertEqual(1.0, graph.closure_ratio)

    def test_stale_evidence_is_rejected_after_obligation_revision(self) -> None:
        obligation = ProofObligation("AC-001", "tests pass", required_authority="DETERMINISTIC_CHECK", revision=2)
        graph = ProofGraph(obligations=[obligation])

        graph.record(Evidence("ev-1", "AC-001", "DETERMINISTIC_CHECK", "old-checks.json", revision=1))

        self.assertEqual("OPEN", obligation.status)
        self.assertEqual("STALE_EVIDENCE", obligation.last_reason)


if __name__ == "__main__":
    unittest.main()
