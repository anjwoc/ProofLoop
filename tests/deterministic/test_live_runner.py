from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class LiveRunnerContractTest(unittest.TestCase):
    def test_fake_claude_without_run_artifacts_fails_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "claude"
            fake.write_text("#!/bin/sh\necho '{\"type\":\"result\"}'\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            completed = subprocess.run(
                ["python3", "scripts/run_claude_live.py", "--claude-bin", str(fake), "--max-budget-usd", "0.01"],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("NO_PROOFLOOP_RUN", completed.stdout)

    def test_fake_codex_without_run_artifacts_fails_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "codex"
            fake.write_text("#!/bin/sh\necho '{\"type\":\"turn.completed\"}'\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            completed = subprocess.run(
                ["python3", "scripts/run_host_live.py", "--host", "codex", "--binary", str(fake)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("NO_PROOFLOOP_RUN", completed.stdout)

    def test_fake_antigravity_without_run_artifacts_fails_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "agy"
            fake.write_text("#!/bin/sh\necho done\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            completed = subprocess.run(
                ["python3", "scripts/run_host_live.py", "--host", "antigravity", "--binary", str(fake)],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("NO_PROOFLOOP_RUN", completed.stdout)


if __name__ == "__main__":
    unittest.main()
