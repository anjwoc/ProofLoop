from __future__ import annotations

import unittest

from proofloop_core.engine.strategy import classify_request, reclassify_after_diff
from proofloop_core.engine.intent_gate import IntentGateResult, IntentKind, ClarityLevel, AuthorityLevel

_MUTATE_RESULT = IntentGateResult(
    intent_kind=IntentKind.MUTATE,
    clarity=ClarityLevel.CLEAR,
    authority=AuthorityLevel.REPOSITORY_MUTATION,
    confidence=1.0,
    signals=(),
    grounding_required=True,
    owner_question=None,
    blocked_reason=None
)

_INVESTIGATE_RESULT = IntentGateResult(
    intent_kind=IntentKind.INVESTIGATE,
    clarity=ClarityLevel.CLEAR,
    authority=AuthorityLevel.READ_ONLY,
    confidence=1.0,
    signals=(),
    grounding_required=True,
    owner_question=None,
    blocked_reason=None
)

class StrategyTest(unittest.TestCase):
    def test_defaults_low_complexity_mutation_to_t1_fast_lane(self) -> None:
        result = classify_request("Implement a new cache invalidation feature across the service and repository", intent_gate_result=_MUTATE_RESULT)
        self.assertEqual("PLANNED_IMPLEMENTATION", result.strategy)
        self.assertEqual("T2", result.tier)
        self.assertTrue(result.planner_required)

        local = classify_request("Add a helper that returns the configured cache name", intent_gate_result=_MUTATE_RESULT)
        self.assertEqual("T1", local.tier)
        self.assertFalse(local.planner_required)
        self.assertFalse(local.reviewer_required)

    def test_high_risk_detection(self) -> None:
        result = classify_request("Fix the payment idempotency race condition", intent_gate_result=_MUTATE_RESULT)
        self.assertEqual("HIGH_RISK_ENGINEERING", result.strategy)
        self.assertEqual("high", result.risk)

    def test_read_only_analysis(self) -> None:
        result = classify_request("Analyze the repository architecture and explain the request flow", intent_gate_result=_INVESTIGATE_RESULT)
        self.assertEqual("REPOSITORY_ANALYSIS", result.strategy)

    def test_direct_override(self) -> None:
        result = classify_request("change it", "DIRECT_VERIFIED_CHANGE", intent_gate_result=_MUTATE_RESULT)
        self.assertEqual("DIRECT_VERIFIED_CHANGE", result.strategy)
        self.assertFalse(result.planner_required)

    def test_small_bounded_change_uses_t0_without_deep_review(self) -> None:
        result = classify_request("README 오타 한 줄만 수정해줘", intent_gate_result=_MUTATE_RESULT)

        self.assertEqual("T0", result.tier)
        self.assertFalse(result.explorer_required)
        self.assertFalse(result.planner_required)
        self.assertFalse(result.reviewer_required)

    def test_cross_cutting_uncertain_change_uses_t2(self) -> None:
        result = classify_request(
            "Implement an unfamiliar cache invalidation feature across API, worker, and database layers",
            intent_gate_result=_MUTATE_RESULT
        )

        self.assertEqual("T2", result.tier)
        self.assertTrue(result.explorer_required)
        self.assertTrue(result.planner_required)
        self.assertTrue(result.reviewer_required)
        self.assertGreaterEqual(result.scores["complexity"], 2)

    def test_known_cross_cutting_t2_skips_explorer_but_keeps_planner_and_review(self) -> None:
        result = classify_request("Implement a cache change across API, worker, and database layers", intent_gate_result=_MUTATE_RESULT)

        self.assertEqual("T2", result.tier)
        self.assertFalse(result.explorer_required)
        self.assertTrue(result.planner_required)
        self.assertTrue(result.reviewer_required)

    def test_security_signal_is_hard_gate_to_t3(self) -> None:
        result = classify_request("로그인 인증 권한 검사를 한 줄 수정해줘", intent_gate_result=_MUTATE_RESULT)

        self.assertEqual("T3", result.tier)
        self.assertEqual("HIGH_RISK_ENGINEERING", result.strategy)
        self.assertTrue(result.hard_gates)

    def test_first_diff_upgrades_underestimated_cross_cutting_work(self) -> None:
        initial = classify_request("README 오타 한 줄만 수정해줘", intent_gate_result=_MUTATE_RESULT)

        revised = reclassify_after_diff(
            initial,
            ["api/routes.py", "worker/jobs.py", "storage/models.py", "tests/test_flow.py"],
        )

        self.assertEqual("T2", revised.tier)
        self.assertTrue(revised.reviewer_required)
        self.assertIn("FIRST_DIFF_CROSS_CUTTING", revised.hard_gates)

    def test_greenfield_persistent_service_is_t3(self) -> None:
        result = classify_request("Build a new project for a reservation service with persistent state and concurrency", intent_gate_result=_MUTATE_RESULT)

        self.assertEqual("T3", result.tier)
        self.assertTrue(result.planner_required)
        self.assertTrue(result.reviewer_required)

        greenfield = classify_request("Create a new project that renders a static status page", intent_gate_result=_MUTATE_RESULT)
        self.assertEqual("T2", greenfield.tier)

    def test_repository_facts_raise_public_contract_change_to_t2(self) -> None:
        result = classify_request(
            "Add the requested helper",
            repository_signals={
                "targetFileCount": 3,
                "matchingTestCount": 0,
                "publicContract": True,
                "persistentState": False,
                "criticalPath": False,
            },
            intent_gate_result=_MUTATE_RESULT,
        )

        self.assertEqual("T2", result.tier)
        self.assertTrue(result.planner_required)
        self.assertTrue(result.reviewer_required)
        self.assertEqual(3, result.repository_signals["targetFileCount"])


if __name__ == "__main__":
    unittest.main()
