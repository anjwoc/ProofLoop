from __future__ import annotations

import unittest

from proofloop_core.engine.repair import decide_next


class RepairDecisionTest(unittest.TestCase):
    def test_repeated_fast_failure_escalates_without_same_role_retry(self) -> None:
        first = [{
            "role": "implementer_fast",
            "checkVerdict": "FAIL",
            "diffVerdict": "PASS",
            "failureFingerprint": "first",
        }]
        self.assertEqual("RUN_FAST", decide_next(first, 2, 1)["action"])

        changed = first + [{
            "role": "implementer_fast",
            "checkVerdict": "FAIL",
            "diffVerdict": "PASS",
            "failureFingerprint": "second",
        }]
        self.assertEqual("RUN_RECOVERY", decide_next(changed, 2, 1)["action"])

        recovery = changed + [{
            "role": "implementer_recovery",
            "checkVerdict": "FAIL",
            "diffVerdict": "PASS",
            "failureFingerprint": "third",
        }]
        self.assertEqual("BLOCKED", decide_next(recovery, 2, 1)["action"])

    def test_identical_fast_failure_switches_to_recovery_immediately(self) -> None:
        attempts = [
            {"role": "implementer_fast", "checkVerdict": "FAIL", "diffVerdict": "PASS", "failureFingerprint": "same"},
            {"role": "implementer_fast", "checkVerdict": "FAIL", "diffVerdict": "PASS", "failureFingerprint": "same"},
        ]
        decision = decide_next(attempts, 3, 1)
        self.assertEqual("RUN_RECOVERY", decision["action"])
        self.assertEqual("R30_IDENTICAL_FAST_TO_RECOVERY", decision["ruleId"])

    def test_design_conflict_returns_to_planner(self) -> None:
        attempts = [{
            "role": "implementer_fast",
            "checkVerdict": "FAIL",
            "diffVerdict": "PASS",
            "classification": "DESIGN_CONFLICT",
        }]
        self.assertEqual("RETURN_TO_PLANNER", decide_next(attempts, 1, 0)["action"])


if __name__ == "__main__":
    unittest.main()
