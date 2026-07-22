from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from proofloop_core.context.io import write_json

SOURCE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt", ".go", ".rs", ".cs", ".rb", ".php", ".sql"}
SKIP = {".git", ".proofloop", ".codegraph", "node_modules", "dist", "build", "target", ".venv", "venv"}


def _has_source(root: Path) -> bool:
    return any(
        f.suffix in SOURCE_SUFFIXES
        for f in root.rglob("*")
        if f.is_file() and not any(p in SKIP for p in f.parts)
    )


def get_files_by_extension(root: str | Path, extensions: Iterable[str]) -> list[Path]:
    normalized = {f".{ext.strip().lstrip('.')}" for ext in extensions}
    root_path = Path(root).resolve()
    return sorted(
        f for f in root_path.rglob("*")
        if f.is_file() and f.suffix in normalized and not any(p in SKIP for p in f.parts)
    )


def ensure_codegraph(repository: str | Path, output: str | Path, *, required: bool = True, mock: bool = False) -> dict[str, Any]:
    repo = Path(repository).resolve()
    target = Path(output)
    result: dict[str, Any]
    if not _has_source(repo):
        result = {"status": "NOT_APPLICABLE", "provider": "codegraph", "repository": str(repo)}
        write_json(target, result)
        return result
    executable = shutil.which("codegraph")
    import os  # ponytail: local import avoids top-level os dep for one env check
    if mock:
        if os.environ.get("PROOFLOOP_ALLOW_MOCK_CONTEXT") != "1":
            # A mock index fabricates a READY status without indexing anything.
            # Refuse unless explicitly opted in, so it can never leak into a
            # real run or a proven claim.
            result = {
                "status": "BLOCKED",
                "provider": "codegraph",
                "reason": "MOCK_CONTEXT_NOT_ALLOWED",
                "repository": str(repo),
            }
            write_json(target, result)
            return result
        index = repo / ".codegraph" / "codegraph.db"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.touch()
        result = {"status": "READY", "provider": "codegraph", "action": "MOCK", "repository": str(repo), "database": str(index)}
        write_json(target, result)
        return result
    if not executable:
        result = {"status": "BLOCKED" if required else "UNAVAILABLE", "provider": "codegraph", "reason": "INDEX_TOOL_REQUIRED", "repository": str(repo)}
        write_json(target, result)
        return result
    action = "sync" if (repo / ".codegraph").exists() else "init"
    commands = [[executable, action, str(repo)], [executable, "status", str(repo)]]
    evidence: list[dict[str, Any]] = []
    for command in commands:
        completed = subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False, timeout=300)
        evidence.append({"command": command, "exitCode": completed.returncode, "stdout": completed.stdout[-4000:], "stderr": completed.stderr[-4000:]})
        if completed.returncode != 0:
            result = {"status": "BLOCKED", "provider": "codegraph", "action": action.upper(), "repository": str(repo), "commands": evidence}
            write_json(target, result)
            return result
    database = repo / ".codegraph" / "codegraph.db"
    result = {
        "status": "READY" if database.exists() else "BLOCKED",
        "provider": "codegraph",
        "action": action.upper(),
        "repository": str(repo),
        "database": str(database),
        "commands": evidence,
    }
    write_json(target, result)
    return result
