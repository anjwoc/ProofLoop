from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proofloop_core.checks import run_checks
from proofloop_core.task_brief import load_task_brief


class CheckRunnerTest(unittest.TestCase):
    def test_exit_code_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = root / "task.json"
            task_path.write_text(json.dumps({
                "id": "TASK-1",
                "objective": "prove failure",
                "allowedPaths": [],
                "protectedPaths": [],

                "changeBudget": {"maxChangedFiles": 8, "maxAddedLines": 500, "maxNewFiles": 4, "allowDependencyChanges": False},
                "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "bounded fixture change", "considered": ["reuse existing test harness"]},
                "requiredChecks": [{"command": ["python3", "-c", "import sys; print('no'); sys.exit(7)"]}]
            }), encoding="utf-8")
            report = run_checks(load_task_brief(task_path), root, root / "evidence")
            self.assertEqual("FAIL", report["verdict"])
            self.assertEqual(7, report["checks"][0]["exitCode"])
            self.assertTrue(Path(report["checks"][0]["stdoutRef"]).exists())


if __name__ == "__main__":
    unittest.main()
