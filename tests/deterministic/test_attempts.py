from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proofloop_core.context.io import write_json
from proofloop_core.engine.attempts import record_attempt


def _task_payload(*, fast: int = 2, recovery: int = 1) -> dict:
    return {
        "id": "TASK-1",
        "objective": "x",
        "allowedPaths": [],
        "protectedPaths": [],
        "changeBudget": {
            "maxChangedFiles": 8,
            "maxAddedLines": 500,
            "maxNewFiles": 4,
            "allowDependencyChanges": False,
        },
        "simplicity": {
            "selectedRung": "DIRECT_CHANGE",
            "rationale": "bounded fixture change",
            "considered": ["REUSE_EXISTING", "STDLIB", "PLATFORM_NATIVE", "INSTALLED_DEPENDENCY"],
            "evidenceRefs": ["fixture#/bounded-change"],
            "permittedNewArtifacts": [],
        },
        "requiredChecks": [{"command": ["python3", "-c", "pass"]}],
        "budgets": {"maxFastAttempts": fast, "maxRecoveryAttempts": recovery},
    }


def _write_failure(root: Path) -> None:
    (root / "checks").mkdir(exist_ok=True)
    stderr = root / "stderr.log"
    stdout = root / "stdout.log"
    stderr.write_text("AssertionError: nope\n", encoding="utf-8")
    stdout.write_text("", encoding="utf-8")
    write_json(root / "checks" / "checks.json", {
        "verdict": "FAIL",
        "checks": [{
            "name": "test",
            "command": ["x"],
            "exitCode": 1,
            "status": "FAIL",
            "stdoutRef": str(stdout),
            "stderrRef": str(stderr),
        }],
    })
    write_json(root / "diff-guard.json", {"verdict": "PASS"})


class AttemptRecorderTest(unittest.TestCase):
    def test_attempt_is_derived_from_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            task.write_text(json.dumps(_task_payload()), encoding="utf-8")
            _write_failure(root)

            result = record_attempt(task, root, "implementer_fast")

            self.assertEqual("RUN_FAST", result["decision"]["action"])
            self.assertEqual("R40_FAST_BUDGET", result["decision"]["ruleId"])
            self.assertTrue(result["attempt"]["failureFingerprint"])

    def test_classification_enables_return_to_planner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            task.write_text(json.dumps(_task_payload()), encoding="utf-8")
            _write_failure(root)

            result = record_attempt(task, root, "implementer_fast", classification="DESIGN_CONFLICT")

            self.assertEqual("DESIGN_CONFLICT", result["attempt"]["classification"])
            self.assertEqual("RETURN_TO_PLANNER", result["decision"]["action"])
            self.assertEqual("R20_OWNER_DECISION", result["decision"]["ruleId"])

    def test_classification_enables_new_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            task.write_text(json.dumps(_task_payload()), encoding="utf-8")
            (root / "checks").mkdir()
            write_json(root / "checks" / "checks.json", {"verdict": "FAIL", "checks": []})
            write_json(root / "diff-guard.json", {"verdict": "PASS"})

            result = record_attempt(
                task,
                root,
                "implementer_fast",
                classification="REPEATED_FAILURE_INVALIDATES_HYPOTHESIS",
            )

            self.assertEqual("RETURN_TO_PLANNER", result["decision"]["action"])

    def test_identical_fast_failure_switches_role_without_same_role_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            task.write_text(json.dumps(_task_payload(fast=3, recovery=1)), encoding="utf-8")
            _write_failure(root)

            first = record_attempt(task, root, "implementer_fast")
            self.assertEqual("RUN_FAST", first["decision"]["action"])

            second = record_attempt(task, root, "implementer_fast")
            self.assertEqual("RUN_RECOVERY", second["decision"]["action"])
            self.assertEqual("R30_IDENTICAL_FAST_TO_RECOVERY", second["decision"]["ruleId"])

    def test_identical_recovery_failure_blocks_without_magic_repeat_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = root / "task.json"
            task.write_text(json.dumps(_task_payload(fast=1, recovery=2)), encoding="utf-8")
            _write_failure(root)

            first = record_attempt(task, root, "implementer_recovery")
            self.assertEqual("RUN_RECOVERY", first["decision"]["action"])

            second = record_attempt(task, root, "implementer_recovery")
            self.assertEqual("BLOCKED", second["decision"]["action"])
            self.assertEqual("R31_IDENTICAL_FAILURE_BLOCK", second["decision"]["ruleId"])
            self.assertIn("BLOCKED_IDENTICAL_FAILURE", second["decision"]["reason"])


if __name__ == "__main__":
    unittest.main()
