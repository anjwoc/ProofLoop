from __future__ import annotations

import unittest

from proofloop_core.reconciler import ReconcilerError, build_conservative_proposal, reconcile_proposal


class ReconcilerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.shadow = {
            "schemaVersion": "1.0",
            "acceptanceCriteria": [{"id": "AC-1"}],
            "facts": [{"id": "F-1"}],
            "openQuestions": [{"id": "Q-1", "blocking": True}, {"id": "Q-2", "blocking": False}],
            "unknowns": ["Root cause"],
            "authorizationBoundary": "src/",
        }

    def test_valid_proposal(self) -> None:
        proposal = dict(self.shadow)
        self.assertEqual(reconcile_proposal(self.shadow, proposal), proposal)

    def test_invented_criteria_rejected(self) -> None:
        proposal = dict(self.shadow, acceptanceCriteria=[{"id": "AC-1"}, {"id": "AC-INVENTED"}])
        with self.assertRaisesRegex(ReconcilerError, "invented criteria rejected"):
            reconcile_proposal(self.shadow, proposal)

    def test_invented_facts_rejected(self) -> None:
        proposal = dict(self.shadow, facts=[{"id": "F-1"}, {"id": "F-INVENTED"}])
        with self.assertRaisesRegex(ReconcilerError, "invented facts rejected"):
            reconcile_proposal(self.shadow, proposal)

    def test_dropped_open_question_rejected(self) -> None:
        proposal = dict(self.shadow, openQuestions=[{"id": "Q-1", "blocking": True}])
        with self.assertRaisesRegex(ReconcilerError, "dropped open question"):
            reconcile_proposal(self.shadow, proposal)

    def test_downgraded_blocking_question_rejected(self) -> None:
        proposal = dict(self.shadow, openQuestions=[{"id": "Q-1", "blocking": False}, {"id": "Q-2", "blocking": False}])
        with self.assertRaisesRegex(ReconcilerError, "downgraded blocking question"):
            reconcile_proposal(self.shadow, proposal)

    def test_hidden_unknowns_rejected(self) -> None:
        proposal = dict(self.shadow, unknowns=[])
        with self.assertRaisesRegex(ReconcilerError, "dropped unknowns"):
            reconcile_proposal(self.shadow, proposal)

    def test_auth_boundary_changed_rejected(self) -> None:
        proposal = dict(self.shadow, authorizationBoundary="src/ and lib/")
        with self.assertRaisesRegex(ReconcilerError, "authorization boundary changed"):
            reconcile_proposal(self.shadow, proposal)

    def test_dropped_criterion_rejected(self) -> None:
        proposal = dict(self.shadow, acceptanceCriteria=[])
        with self.assertRaisesRegex(ReconcilerError, "dropped acceptance criterion"):
            reconcile_proposal(self.shadow, proposal)

    def test_conservative_proposal_constrains_only_declared_scope(self) -> None:
        shadow = {
            **self.shadow,
            "kind": "EXECUTION_BRIEF_SHADOW",
            "scope": {
                "candidates": ["src/value.py"],
                "approvedPaths": [],
                "protectedPaths": [],
                "status": "UNRESOLVED",
            },
        }
        proposal = build_conservative_proposal(shadow)
        self.assertEqual("EXECUTION_BRIEF", proposal["kind"])
        self.assertEqual(["src/value.py"], proposal["scope"]["approvedPaths"])
        self.assertEqual(proposal, reconcile_proposal(shadow, proposal))

        proposal["scope"]["approvedPaths"].append("outside.py")
        with self.assertRaisesRegex(ReconcilerError, "outside candidates"):
            reconcile_proposal(shadow, proposal)


if __name__ == "__main__":
    unittest.main()
