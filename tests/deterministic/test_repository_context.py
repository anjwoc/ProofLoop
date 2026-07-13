from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from proofloop_core.repository_context import ensure_codegraph


class RepositoryContextTest(unittest.TestCase):
    def test_mock_initializes_index_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('x')\n", encoding="utf-8")
            result = ensure_codegraph(root, root / "evidence.json", mock=True)
            self.assertEqual("READY", result["status"])
            self.assertTrue((root / ".codegraph" / "codegraph.db").exists())


if __name__ == "__main__":
    unittest.main()
