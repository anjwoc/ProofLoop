from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from proofloop_core.context.git_snapshot import snapshot_worktree
from proofloop_core.context.worktree_sandbox import (
    GitWorktreeSandbox,
    SandboxPromotionError,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _repository(root: Path) -> str:
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "src").mkdir()
    (root / "src" / "value.txt").write_text("before\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "baseline")
    return snapshot_worktree(root)


def test_verified_changes_are_promoted_only_after_explicit_promotion(
    tmp_path: Path,
) -> None:
    baseline = _repository(tmp_path)
    evidence = tmp_path / ".proofloop" / "sandbox-test"

    with GitWorktreeSandbox(tmp_path, baseline, evidence) as sandbox:
        (sandbox.path / "src" / "value.txt").write_text("after\n", encoding="utf-8")
        (sandbox.path / "src" / "new.txt").write_text("new\n", encoding="utf-8")

        assert (tmp_path / "src" / "value.txt").read_text(encoding="utf-8") == "before\n"
        result = sandbox.promote(("src/**",))

        assert result["changedPaths"] == ["src/new.txt", "src/value.txt"]
        sandbox_path = sandbox.path

    assert not sandbox_path.exists()
    assert (tmp_path / "src" / "value.txt").read_text(encoding="utf-8") == "after\n"
    assert (tmp_path / "src" / "new.txt").read_text(encoding="utf-8") == "new\n"
    assert (evidence / "promotion.patch").is_file()


def test_out_of_scope_change_is_not_promoted(tmp_path: Path) -> None:
    baseline = _repository(tmp_path)
    evidence = tmp_path / ".proofloop" / "sandbox-test"

    with GitWorktreeSandbox(tmp_path, baseline, evidence) as sandbox:
        (sandbox.path / "README.md").write_text("escape\n", encoding="utf-8")

        with pytest.raises(SandboxPromotionError, match="outside allowed paths"):
            sandbox.promote(("src/**",))

    assert not (tmp_path / "README.md").exists()


def test_concurrent_original_change_blocks_promotion(tmp_path: Path) -> None:
    baseline = _repository(tmp_path)
    evidence = tmp_path / ".proofloop" / "sandbox-test"

    with GitWorktreeSandbox(tmp_path, baseline, evidence) as sandbox:
        (sandbox.path / "src" / "value.txt").write_text("sandbox\n", encoding="utf-8")
        (tmp_path / "src" / "value.txt").write_text("owner\n", encoding="utf-8")

        with pytest.raises(SandboxPromotionError, match="changed during isolated execution"):
            sandbox.promote(("src/**",))

    assert (tmp_path / "src" / "value.txt").read_text(encoding="utf-8") == "owner\n"
