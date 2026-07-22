from __future__ import annotations

import unittest

from proofloop_core.engine.repair import decide_next


class RepairDecisionTest(unittest.TestCase):
    def test_repeated_fast_failure_escalates(self) -> None:
        first = [{"role": "implementer_fast", "checkVerdict": "FAIL", "diffVerdict": "PASS", "failureFingerprint": "same"}]
        self.assertEqual("RETRY_FAST", decide_next(first)["action"])
        second = first + [{"role": "implementer_fast", "checkVerdict": "FAIL", "diffVerdict": "PASS", "failureFingerprint": "same"}]
        self.assertEqual("RUN_RECOVERY", decide_next(second)["action"])
        recovery = second + [{"role": "implementer_recovery", "checkVerdict": "FAIL", "diffVerdict": "PASS", "failureFingerprint": "same"}]
        self.assertEqual("BLOCKED", decide_next(recovery)["action"])

    def test_design_conflict_returns_to_planner(self) -> None:
        attempts = [{"role": "implementer_fast", "checkVerdict": "FAIL", "diffVerdict": "PASS", "classification": "DESIGN_CONFLICT"}]
        self.assertEqual("RETURN_TO_PLANNER", decide_next(attempts)["action"])


if __name__ == "__main__":
    unittest.main()
