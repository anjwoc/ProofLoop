from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from proofloop_core.git_snapshot import snapshot_worktree


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def make_repo(root: Path, *, track_proofloop: bool = False) -> None:
    git(root, "init")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / ".gitignore").write_text(".proofloop/\n", encoding="utf-8")
    (root / "app.txt").write_text("baseline\n", encoding="utf-8")
    git(root, "add", ".gitignore", "app.txt")
    if track_proofloop:
        (root / ".proofloop").mkdir()
        (root / ".proofloop" / "legacy.txt").write_text("legacy\n", encoding="utf-8")
        git(root, "add", "-f", ".proofloop/legacy.txt")
    git(root, "commit", "-m", "baseline")


class GitSnapshotTest(unittest.TestCase):
    def test_snapshot_succeeds_when_proofloop_evidence_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            (root / "app.txt").write_text("worktree change\n", encoding="utf-8")
            (root / "staged.txt").write_text("staged\n", encoding="utf-8")
            git(root, "add", "staged.txt")
            evidence = root / ".proofloop" / "runs" / "run-1" / "events.jsonl"
            evidence.parent.mkdir(parents=True)
            evidence.write_text('{"type":"run.started"}\n', encoding="utf-8")
            index_before = git(root, "write-tree")

            baseline = snapshot_worktree(root)

            self.assertEqual("worktree change", git(root, "show", f"{baseline}:app.txt"))
            self.assertEqual("staged", git(root, "show", f"{baseline}:staged.txt"))
            paths = git(root, "ls-tree", "-r", "--name-only", baseline).splitlines()
            self.assertFalse(any(path == ".proofloop" or path.startswith(".proofloop/") for path in paths))
            self.assertEqual(index_before, git(root, "write-tree"))

    def test_snapshot_removes_previously_tracked_proofloop_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root, track_proofloop=True)

            baseline = snapshot_worktree(root)

            paths = git(root, "ls-tree", "-r", "--name-only", baseline).splitlines()
            self.assertNotIn(".proofloop/legacy.txt", paths)


if __name__ == "__main__":
    unittest.main()
