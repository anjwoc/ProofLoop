from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _run(repo: Path, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False)
    return {
        "command": command,
        "exitCode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def preflight(repository: str | Path) -> dict[str, Any]:
    repo = Path(repository).resolve()
    git_root_result = _run(repo, ["git", "rev-parse", "--show-toplevel"])
    is_git = git_root_result["exitCode"] == 0
    root = Path(git_root_result["stdout"]).resolve() if is_git else repo
    status = _run(root, ["git", "status", "--porcelain=v1"]) if is_git else None
    markers = {
        "node": (root / "package.json").exists(),
        "python": any((root / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py")),
        "java": any((root / name).exists() for name in ("pom.xml", "build.gradle", "build.gradle.kts")),
        "go": (root / "go.mod").exists(),
        "rust": (root / "Cargo.toml").exists(),
    }
    codegraph = shutil.which("codegraph")
    codegraph_version = None
    if codegraph:
        result = _run(root, [codegraph, "version"])
        codegraph_version = result["stdout"] or result["stderr"]
    return {
        "schemaVersion": "1.0",
        "repository": str(root),
        "isGitRepository": is_git,
        "gitStatus": status,
        "projectMarkers": markers,
        "codegraph": {
            "available": bool(codegraph),
            "path": codegraph,
            "version": codegraph_version,
        },
    }
