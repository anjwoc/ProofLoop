from __future__ import annotations

import fnmatch
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

from proofloop_core.context.git_snapshot import changed_source_files, snapshot_worktree
from proofloop_core.context.io import write_json


class SandboxPromotionError(RuntimeError):
    pass


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SandboxPromotionError(
            result.stderr.strip() or f"git {' '.join(args)} failed"
        )
    return result.stdout.strip()


def _matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(
        fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("*/"))
        for pattern in patterns
    )


class GitWorktreeSandbox:
    def __init__(
        self,
        repository: str | Path,
        baseline_commit: str,
        evidence_dir: str | Path,
    ) -> None:
        self.repository = Path(repository).resolve()
        self.baseline_commit = baseline_commit
        self.evidence_dir = Path(evidence_dir).resolve()
        self.path = Path()
        self._entered = False

    def __enter__(self) -> "GitWorktreeSandbox":
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="proofloop-worktree-"))
        temporary.rmdir()
        self.path = temporary
        try:
            _git(
                self.repository,
                "worktree",
                "add",
                "--detach",
                str(self.path),
                self.baseline_commit,
            )
        except Exception:
            shutil.rmtree(self.path, ignore_errors=True)
            raise
        self._entered = True
        write_json(
            self.evidence_dir / "sandbox.json",
            {
                "schemaVersion": "1.0",
                "status": "ACTIVE",
                "repository": str(self.repository),
                "workspace": str(self.path),
                "baselineCommit": self.baseline_commit,
            },
        )
        return self

    def promote(self, allowed_paths: Iterable[str]) -> dict[str, object]:
        if not self._entered:
            raise SandboxPromotionError("sandbox is not active")
        patterns = tuple(str(pattern) for pattern in allowed_paths)
        changed = changed_source_files(self.path, self.baseline_commit)
        outside = [path for path in changed if not _matches(path, patterns)]
        if outside:
            raise SandboxPromotionError(
                f"isolated changes are outside allowed paths: {', '.join(outside)}"
            )

        current = snapshot_worktree(self.repository)
        baseline_tree = _git(
            self.repository,
            "rev-parse",
            f"{self.baseline_commit}^{{tree}}",
        )
        current_tree = _git(self.repository, "rev-parse", f"{current}^{{tree}}")
        if current_tree != baseline_tree:
            raise SandboxPromotionError(
                "original worktree changed during isolated execution"
            )

        verified = snapshot_worktree(self.path)
        patch_path = self.evidence_dir / "promotion.patch"
        with patch_path.open("wb") as patch:
            result = subprocess.run(
                [
                    "git",
                    "diff",
                    "--binary",
                    self.baseline_commit,
                    verified,
                    "--",
                ],
                cwd=self.path,
                stdout=patch,
                stderr=subprocess.PIPE,
                check=False,
            )
        if result.returncode != 0:
            raise SandboxPromotionError(
                result.stderr.decode("utf-8", errors="replace").strip()
                or "could not build verified promotion patch"
            )
        if patch_path.stat().st_size:
            _git(self.repository, "apply", "--check", "--binary", str(patch_path))
            _git(self.repository, "apply", "--binary", str(patch_path))

        report = {
            "schemaVersion": "1.0",
            "status": "PROMOTED",
            "baselineCommit": self.baseline_commit,
            "verifiedCommit": verified,
            "changedPaths": changed,
            "patch": str(patch_path),
        }
        write_json(self.evidence_dir / "promotion.json", report)
        return report

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if not self._entered:
            return
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(self.path)],
            cwd=self.repository,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            shutil.rmtree(self.path, ignore_errors=True)
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=self.repository,
                capture_output=True,
                check=False,
            )
        self._entered = False
