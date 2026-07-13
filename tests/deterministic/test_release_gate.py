from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ReleaseGateTest(unittest.TestCase):
    def test_release_fails_without_live_proof(self) -> None:
        completed = subprocess.run(["python3", "scripts/release_check.py"], cwd=ROOT, env={**os.environ, "PROOFLOOP_RELEASE_CHECK_TEST_MODE": "1"}, capture_output=True, text=True, check=False)
        self.assertNotEqual(0, completed.returncode)
        self.assertIn('"overallRelease": "FAIL"', completed.stdout)

    def test_development_check_can_pass_without_claiming_release(self) -> None:
        completed = subprocess.run(["python3", "scripts/release_check.py", "--development"], cwd=ROOT, env={**os.environ, "PROOFLOOP_RELEASE_CHECK_TEST_MODE": "1"}, capture_output=True, text=True, check=False)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn('"overallRelease": "FAIL"', completed.stdout)


if __name__ == "__main__":
    unittest.main()
