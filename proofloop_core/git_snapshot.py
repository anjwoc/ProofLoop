from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout.strip()


def snapshot_worktree(repository: str | Path) -> str:
    """Create an unreachable commit object representing the current worktree.

    A temporary index is used so the user's real index and branch are not changed.
    `.proofloop/` evidence is intentionally excluded.
    """

    repo = Path(repository).resolve()
    _git(repo, "rev-parse", "--is-inside-work-tree")
    with tempfile.NamedTemporaryFile(prefix="proofloop-index-", delete=False) as handle:
        index_path = Path(handle.name)
    try:
        index_path.unlink(missing_ok=True)
        env = {
            **os.environ,
            "GIT_INDEX_FILE": str(index_path),
            "GIT_AUTHOR_NAME": "ProofLoop",
            "GIT_AUTHOR_EMAIL": "proofloop@local.invalid",
            "GIT_COMMITTER_NAME": "ProofLoop",
            "GIT_COMMITTER_EMAIL": "proofloop@local.invalid",
        }
        head = _git(repo, "rev-parse", "--verify", "HEAD", env=env)
        _git(repo, "read-tree", head, env=env)
        _git(repo, "add", "-A", "--", ".", ":(exclude).proofloop", ":(exclude).proofloop/**", env=env)
        tree = _git(repo, "write-tree", env=env)
        commit = _git(repo, "commit-tree", tree, "-p", head, "-m", "ProofLoop ephemeral baseline", env=env)
        return commit
    finally:
        index_path.unlink(missing_ok=True)


def _is_ephemeral_generated(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    return (
        "__pycache__" in parts
        or ".pytest_cache" in parts
        or ".mypy_cache" in parts
        or ".ruff_cache" in parts
        or normalized.endswith(".pyc")
        or normalized.endswith(".pyo")
        or Path(normalized).name in {".coverage", ".DS_Store"}
    )


def changed_source_files(repository: str | Path, baseline: str) -> list[str]:
    repo = Path(repository).resolve()
    output = _git(repo, "diff", "--name-only", baseline, "--")
    changed = [line.strip() for line in output.splitlines() if line.strip()]
    untracked = _git(repo, "ls-files", "--others", "--exclude-standard")
    changed.extend(line.strip() for line in untracked.splitlines() if line.strip())
    return sorted({
        path for path in changed
        if not path.startswith(".proofloop") and not _is_ephemeral_generated(path)
    })
