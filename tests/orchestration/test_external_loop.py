from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from proofloop_core.engine.external_loop import run_external_loop


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class ExternalLoopTest(unittest.TestCase):
    """SIMULATED_ORCHESTRATION: implementers are deterministic fixture scripts."""

    def test_fast_fast_recovery_sequence_is_runtime_owned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            (root / "value.txt").write_text("broken\n", encoding="utf-8")
            (root / "check.py").write_text(
                "from pathlib import Path\n"
                "raise SystemExit(0 if Path('value.txt').read_text().strip() == 'fixed' else 1)\n",
                encoding="utf-8",
            )
            fast = root / "fast.py"
            fast.write_text(
                "import os\nfrom pathlib import Path\n"
                "Path('value.txt').write_text('still-broken-' + os.environ['PROOFLOOP_ATTEMPT'] + '\\n')\n",
                encoding="utf-8",
            )
            recovery = root / "recovery.py"
            recovery.write_text("from pathlib import Path\nPath('value.txt').write_text('fixed\\n')\n", encoding="utf-8")
            task = root / "task.json"
            task.write_text(json.dumps({
                "id": "TASK-LOOP",
                "objective": "fix value",
                "allowedPaths": ["value.txt"],
                "protectedPaths": ["check.py"],

                "changeBudget": {"maxChangedFiles": 8, "maxAddedLines": 500, "maxNewFiles": 4, "allowDependencyChanges": False},
                "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "bounded fixture change", "considered": ["reuse existing test harness"]},
                "requiredChecks": [{"name": "behavior", "command": ["python3", "check.py"]}],
                "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1}
            }), encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            result = run_external_loop(
                task,
                root,
                root / ".proofloop-run",
                ["python3", str(fast)],
                ["python3", str(recovery)],
            )
            self.assertEqual("READY_FOR_REVIEW", result["verdict"])
            roles = [item["role"] for item in result["attempts"]]
            self.assertEqual(["implementer_fast", "implementer_fast", "implementer_recovery"], roles)
            self.assertEqual("fixed", (root / "value.txt").read_text().strip())


if __name__ == "__main__":
    unittest.main()
