from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from proofloop_core.repository_context import ensure_codegraph, get_files_by_extension


class RepositoryContextTest(unittest.TestCase):
    def test_mock_initializes_index_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("print('x')\n", encoding="utf-8")
            result = ensure_codegraph(root, root / "evidence.json", mock=True)
            self.assertEqual("READY", result["status"])
            self.assertTrue((root / ".codegraph" / "codegraph.db").exists())


class GetFilesByExtensionTest(unittest.TestCase):
    def test_single_extension_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("", encoding="utf-8")
            (root / "script.sh").write_text("", encoding="utf-8")
            (root / "index.js").write_text("", encoding="utf-8")
            result = get_files_by_extension(root, [".py"])
            self.assertEqual(1, len(result))
            self.assertTrue(any(f.name == "app.py" for f in result))

    def test_skip_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "hidden.py").write_text("", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "lib.js").write_text("", encoding="utf-8")
            result = get_files_by_extension(root, [".py"])
            self.assertEqual(1, len(result))
            self.assertTrue(any(f.name == "app.py" for f in result))

    def test_no_match_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "script.sh").write_text("", encoding="utf-8")
            (root / "readme.md").write_text("", encoding="utf-8")
            result = get_files_by_extension(root, [".py"])
            self.assertEqual([], result)

    def test_multiple_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("", encoding="utf-8")
            (root / "index.js").write_text("", encoding="utf-8")
            (root / "style.css").write_text("", encoding="utf-8")
            result = get_files_by_extension(root, [".py", ".js"])
            self.assertEqual(2, len(result))
            self.assertEqual({"app.py", "index.js"}, {f.name for f in result})

    def test_extension_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app.py").write_text("", encoding="utf-8")
            (root / "index.js").write_text("", encoding="utf-8")
            r1 = get_files_by_extension(root, [".py"])
            r2 = get_files_by_extension(root, ["py"])
            r3 = get_files_by_extension(root, [".py", "js"])
            self.assertEqual(1, len(r1))
            self.assertEqual(1, len(r2))
            self.assertEqual(2, len(r3))


if __name__ == "__main__":
    unittest.main()
