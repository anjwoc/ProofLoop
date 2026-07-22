from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proofloop_core.engine.attempts import record_attempt
from proofloop_core.context.io import write_json


class AttemptRecorderTest(unittest.TestCase):
    def test_attempt_is_derived_from_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            task.write_text(json.dumps({
                "id": "TASK-1",
                "objective": "x",
                "allowedPaths": [],
                "protectedPaths": [],

                "changeBudget": {"maxChangedFiles": 8, "maxAddedLines": 500, "maxNewFiles": 4, "allowDependencyChanges": False},
                "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "bounded fixture change", "considered": ["reuse existing test harness"]},
                "requiredChecks": [{"command": ["python3", "-c", "pass"]}],
                "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1}
            }), encoding="utf-8")
            (root / "checks").mkdir()
            stderr = root / "stderr.log"
            stdout = root / "stdout.log"
            stderr.write_text("AssertionError: nope\n", encoding="utf-8")
            stdout.write_text("", encoding="utf-8")
            write_json(root / "checks" / "checks.json", {
                "verdict": "FAIL",
                "checks": [{"name": "test", "command": ["x"], "exitCode": 1, "status": "FAIL", "stdoutRef": str(stdout), "stderrRef": str(stderr)}]
            })
            write_json(root / "diff-guard.json", {"verdict": "PASS"})
            result = record_attempt(task, root, "implementer_fast")
            self.assertEqual("RETRY_FAST", result["decision"]["action"])
            self.assertTrue(result["attempt"]["failureFingerprint"])

    def test_classification_enables_return_to_planner(self) -> None:
        # Parity with the orchestrator inline loop: an externally recorded
        # attempt carrying a DESIGN_CONFLICT classification must be able to
        # route back to the planner instead of retrying blindly.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            task.write_text(json.dumps({
                "id": "TASK-1",
                "objective": "x",
                "allowedPaths": [],
                "protectedPaths": [],
                "changeBudget": {"maxChangedFiles": 8, "maxAddedLines": 500, "maxNewFiles": 4, "allowDependencyChanges": False},
                "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "bounded fixture change", "considered": ["reuse existing test harness"]},
                "requiredChecks": [{"command": ["python3", "-c", "pass"]}],
                "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1}
            }), encoding="utf-8")
            (root / "checks").mkdir()
            stderr = root / "stderr.log"
            stdout = root / "stdout.log"
            stderr.write_text("AssertionError: nope\n", encoding="utf-8")
            stdout.write_text("", encoding="utf-8")
            write_json(root / "checks" / "checks.json", {
                "verdict": "FAIL",
                "checks": [{"name": "test", "command": ["x"], "exitCode": 1, "status": "FAIL", "stdoutRef": str(stdout), "stderrRef": str(stderr)}]
            })
            write_json(root / "diff-guard.json", {"verdict": "PASS"})
            result = record_attempt(task, root, "implementer_fast", classification="DESIGN_CONFLICT")
            self.assertEqual("DESIGN_CONFLICT", result["attempt"]["classification"])
            self.assertEqual("RETURN_TO_PLANNER", result["decision"]["action"])

    def test_classification_enables_new_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            task.write_text(json.dumps({
                "id": "TASK-1",
                "objective": "x",
                "allowedPaths": [],
                "protectedPaths": [],
                "changeBudget": {"maxChangedFiles": 8, "maxAddedLines": 500, "maxNewFiles": 4, "allowDependencyChanges": False},
                "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "bounded fixture change", "considered": ["reuse existing test harness"]},
                "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1}
            }), encoding="utf-8")
            (root / "checks").mkdir()
            write_json(root / "checks" / "checks.json", {"verdict": "FAIL", "checks": []})
            write_json(root / "diff-guard.json", {"verdict": "PASS"})
            result = record_attempt(task, root, "implementer_fast", classification="REPEATED_FAILURE_INVALIDATES_HYPOTHESIS")
            self.assertEqual("RETURN_TO_PLANNER", result["decision"]["action"])

    def test_fingerprint_repeats_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            task.write_text(json.dumps({
                "id": "TASK-1",
                "objective": "x",
                "allowedPaths": [],
                "protectedPaths": [],
                "changeBudget": {"maxChangedFiles": 8, "maxAddedLines": 500, "maxNewFiles": 4, "allowDependencyChanges": False},
                "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "bounded fixture change", "considered": ["reuse existing test harness"]},
                "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1}
            }), encoding="utf-8")
            (root / "checks").mkdir()
            stderr = root / "stderr.log"
            stdout = root / "stdout.log"
            stderr.write_text("AssertionError: nope\n", encoding="utf-8")
            stdout.write_text("", encoding="utf-8")
            write_json(root / "checks" / "checks.json", {
                "verdict": "FAIL",
                "checks": [{"name": "test", "command": ["x"], "exitCode": 1, "status": "FAIL", "stdoutRef": str(stdout), "stderrRef": str(stderr)}]
            })
            write_json(root / "diff-guard.json", {"verdict": "PASS"})

            # Attempt 1 -> RETRY_FAST
            result1 = record_attempt(task, root, "implementer_fast")
            self.assertEqual("RETRY_FAST", result1["decision"]["action"])

            # Attempt 2 -> RUN_RECOVERY
            result2 = record_attempt(task, root, "implementer_fast")
            self.assertEqual("RUN_RECOVERY", result2["decision"]["action"])

            # Attempt 3 -> BLOCKED (same fingerprint repeated 3 times)
            result3 = record_attempt(task, root, "implementer_recovery")
            self.assertEqual("BLOCKED", result3["decision"]["action"])
            self.assertEqual("same failure fingerprint repeated 3 times", result3["decision"]["reason"])


if __name__ == "__main__":
    unittest.main()
