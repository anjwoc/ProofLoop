from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proofloop_core.attempts import record_attempt
from proofloop_core.io import write_json


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


if __name__ == "__main__":
    unittest.main()
