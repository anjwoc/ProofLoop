from __future__ import annotations

import unittest

from proofloop_core.strategy import classify_request


class StrategyTest(unittest.TestCase):
    def test_defaults_nontrivial_mutation_to_planned(self) -> None:
        result = classify_request("Implement a new cache invalidation feature across the service and repository")
        self.assertEqual("PLANNED_IMPLEMENTATION", result.strategy)
        self.assertTrue(result.planner_required)

    def test_high_risk_detection(self) -> None:
        result = classify_request("Fix the payment idempotency race condition")
        self.assertEqual("HIGH_RISK_ENGINEERING", result.strategy)
        self.assertEqual("high", result.risk)

    def test_read_only_analysis(self) -> None:
        result = classify_request("Analyze the repository architecture and explain the request flow")
        self.assertEqual("REPOSITORY_ANALYSIS", result.strategy)

    def test_direct_override(self) -> None:
        result = classify_request("change it", "DIRECT_VERIFIED_CHANGE")
        self.assertEqual("DIRECT_VERIFIED_CHANGE", result.strategy)
        self.assertFalse(result.planner_required)


if __name__ == "__main__":
    unittest.main()
