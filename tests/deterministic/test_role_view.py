from __future__ import annotations

import copy
import hashlib
import unittest
from typing import Any

from proofloop_core.contracts.execution_brief import compose_execution_brief
from proofloop_core.contracts.role_view import (
    KNOWN_ROLES,
    RoleViewValidationError,
    project_role_view,
)


def _brief() -> dict[str, Any]:
    """Build a valid shadow brief for testing."""
    request_text = "Fix the login bug"
    request_hash = hashlib.sha256(request_text.encode("utf-8")).hexdigest()
    return compose_execution_brief(
        request_artifact={
            "schemaVersion": "1.0",
            "requestId": "REQ-001",
            "rawText": request_text,
            "rawHash": request_hash,
            "receivedAt": "2026-07-21T00:00:00Z",
            "repoRoot": "/fake/repo",
            "hostRequested": "cli",
            "explicitPermissions": [],
            "explicitDenials": [],
            "userConstraints": [],
            "invocationSource": "test",
        },
        intent_contract={
            "schemaVersion": "1.0",
            "originalRequest": request_text,
            "originalRequestHash": request_hash,
            "objective": "Fix the login bug",
            "acceptanceCriteria": [{"id": "AC-001", "statement": "Login works"}],
            "constraints": ["No breaking changes"],
            "nonGoals": ["UI redesign"],
            "authorizationBoundary": "src/",
            "assumptions": ["Auth module is testable"],
            "unknowns": ["Root cause unclear"],
            "riskSignals": ["Session state corruption"],
            "targetArtifacts": ["src/auth.py"],
        },
        strategy={"schemaVersion": "1.0", "approach": "direct"},
        repository_context={"schemaVersion": "1.0", "status": "SKIPPED"},
        repository_baseline="abc123",
    )


class RoleViewProjectorTest(unittest.TestCase):
    def test_all_known_roles_produce_view(self) -> None:
        brief = _brief()
        for role in KNOWN_ROLES:
            view = project_role_view(brief, role, f"inv-{role}")
            self.assertEqual(view["role"], role)
            self.assertEqual(view["schemaVersion"], "1.0")
            self.assertEqual(view["invocationId"], f"inv-{role}")

    def test_implementer_has_no_raw_transcript(self) -> None:
        view = project_role_view(_brief(), "implementer_fast", "inv-1")
        for forbidden in ("originalRequest", "rawRequest", "transcript", "inferences"):
            self.assertNotIn(forbidden, view)

    def test_explorer_gets_facts_not_criteria(self) -> None:
        view = project_role_view(_brief(), "explorer", "inv-1")
        self.assertIn("objective", view)
        self.assertIn("facts", view)
        self.assertNotIn("acceptanceCriteria", view)

    def test_reviewer_gets_assumptions(self) -> None:
        view = project_role_view(_brief(), "reviewer", "inv-1")
        self.assertIn("assumptions", view)
        self.assertEqual(view["assumptions"], [{"statement": "Auth module is testable", "provenance": "user_explicit"}])

    def test_provenance_has_brief_hash(self) -> None:
        brief = _brief()
        from proofloop_core.contracts.execution_brief import canonical_sha256
        expected = canonical_sha256(dict(brief))
        view = project_role_view(brief, "implementer_fast", "inv-1")
        self.assertEqual(view["provenance"]["executionBriefSha256"], expected)

    def test_provenance_has_proof_graph_fields(self) -> None:
        view = project_role_view(_brief(), "planner_deep", "inv-1")
        self.assertIsNone(view["provenance"]["proofGraphSha256"])
        self.assertEqual(view["provenance"]["obligationRevision"], 0)

    def test_canonical_orchestrator_role_names_accepted(self) -> None:
        # The orchestrator/host_runner use canonical role names; role_view must
        # accept them, not only the short internal aliases.
        brief = _brief()
        for canonical, short in (
            ("explorer_fast", "explorer"),
            ("implementer_recovery", "recovery"),
            ("reviewer_deep", "reviewer"),
        ):
            canonical_view = project_role_view(brief, canonical, f"inv-{canonical}")
            short_view = project_role_view(brief, short, f"inv-{short}")
            def projected(view: dict[str, Any]) -> set[str]:
                return {key for key in view if key not in {"role", "invocationId"}}
            self.assertEqual(projected(canonical_view), projected(short_view))

    def test_reviewer_deep_canonical_gets_assumptions(self) -> None:
        view = project_role_view(_brief(), "reviewer_deep", "inv-1")
        self.assertIn("assumptions", view)

    def test_unknown_role_raises(self) -> None:
        with self.assertRaises(RoleViewValidationError):
            project_role_view(_brief(), "hacker", "inv-1")

    def test_empty_invocation_id_raises(self) -> None:
        with self.assertRaises(RoleViewValidationError):
            project_role_view(_brief(), "explorer", "")

    def test_scope_only_shows_candidates(self) -> None:
        view = project_role_view(_brief(), "implementer_fast", "inv-1")
        self.assertIn("scope", view)
        self.assertIn("candidates", view["scope"])
        self.assertNotIn("approvedPaths", view["scope"])
        self.assertNotIn("status", view["scope"])

    def test_brief_not_mutated(self) -> None:
        brief = _brief()
        snapshot = copy.deepcopy(brief)
        project_role_view(brief, "reviewer", "inv-1")
        self.assertEqual(brief, snapshot)

    def test_same_brief_same_role_same_provenance(self) -> None:
        brief = _brief()
        v1 = project_role_view(brief, "implementer_fast", "inv-1")
        v2 = project_role_view(brief, "implementer_fast", "inv-2")
        self.assertEqual(
            v1["provenance"]["executionBriefSha256"],
            v2["provenance"]["executionBriefSha256"],
        )


if __name__ == "__main__":
    unittest.main()
