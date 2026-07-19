from __future__ import annotations

import re
from pathlib import Path
from typing import Any


_PUBLIC = re.compile(r"(?:^|/)(?:api|routes?|controllers?|public|schemas?|proto)(?:/|\.|$)", re.I)
_PERSISTENT = re.compile(r"(?:^|/)(?:db|database|models?|migrations?|storage)(?:/|\.|$)", re.I)
_CRITICAL = re.compile(r"(?:auth|permission|payment|billing|migration|schema|security|deploy|infra)", re.I)
_CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb", ".php"}


def probe_repository_signals(repository: str | Path, targets: tuple[str, ...]) -> dict[str, Any]:
    root = Path(repository).resolve()
    safe_targets: list[Path] = []
    for value in targets:
        candidate = (root / value).resolve()
        if candidate == root or root not in candidate.parents:
            continue
        if candidate.is_file():
            safe_targets.append(candidate)
    test_files: set[Path] = set()
    for target in safe_targets:
        stem = target.stem.removeprefix("test_")
        for test_root_name in ("tests", "test", "spec"):
            test_root = root / test_root_name
            if not test_root.is_dir():
                continue
            for candidate in test_root.rglob("*"):
                if candidate.is_file() and stem in candidate.stem:
                    test_files.add(candidate)
    relative = [path.relative_to(root).as_posix() for path in safe_targets]
    code_files = 0
    for candidate in root.iterdir() if root.exists() else ():
        if candidate.is_file() and candidate.suffix in _CODE_SUFFIXES:
            code_files += 1
        elif candidate.is_dir() and candidate.name not in {".git", ".proofloop", "node_modules", ".venv"}:
            code_files += sum(
                1
                for path in candidate.rglob("*")
                if path.is_file() and path.suffix in _CODE_SUFFIXES and ".proofloop" not in path.parts
            )
            if code_files > 3:
                break
    joined = "\n".join(relative)
    return {
        "targetFileCount": len(safe_targets),
        "matchingTestCount": len(test_files),
        "publicContract": bool(_PUBLIC.search(joined)),
        "persistentState": bool(_PERSISTENT.search(joined)),
        "criticalPath": bool(_CRITICAL.search(joined)),
        "greenfieldRepository": code_files <= 2,
    }
