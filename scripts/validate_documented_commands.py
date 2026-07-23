#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ROOT / "docs" / "EXPECTED_RESULTS_AND_TEST_SCENARIOS.md",
    ROOT / "docs" / "PIPELINE_EXECUTION_GUIDE.md",
)
PATH_PATTERN = re.compile(
    r"(?<![\w/.-])((?:tests|scripts)/[A-Za-z0-9_./-]+(?:\.py|\.json|\.md)(?:::[A-Za-z0-9_]+)*)"
)


def referenced_paths() -> dict[str, list[str]]:
    references: dict[str, list[str]] = {}
    for document in DOCUMENTS:
        text = document.read_text(encoding="utf-8")
        for raw in PATH_PATTERN.findall(text):
            path = raw.split("::", 1)[0]
            references.setdefault(path, []).append(document.relative_to(ROOT).as_posix())
    return references


def main() -> int:
    missing = {
        path: documents
        for path, documents in referenced_paths().items()
        if not (ROOT / path).is_file()
    }
    if missing:
        print("DOCUMENTED COMMAND VALIDATION: FAIL")
        for path, documents in sorted(missing.items()):
            print(f"- missing {path} (referenced by {', '.join(sorted(set(documents)))})")
        return 1
    print("DOCUMENTED COMMAND VALIDATION: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
