from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from proofloop_core.workload import probe_repository_signals


class WorkloadProbeTest(unittest.TestCase):
    def test_probe_uses_explicit_targets_and_test_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "api").mkdir()
            (root / "tests").mkdir()
            (root / "api" / "routes.py").write_text("routes = []\n")
            (root / "tests" / "test_routes.py").write_text("def test_routes(): pass\n")

            signals = probe_repository_signals(root, ("api/routes.py",))

            self.assertEqual(1, signals["targetFileCount"])
            self.assertEqual(1, signals["matchingTestCount"])
            self.assertTrue(signals["publicContract"])


if __name__ == "__main__":
    unittest.main()
