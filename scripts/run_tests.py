#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_arguments() -> list[str]:
    """Return the canonical test collection used by development and release gates."""
    return [
        str(ROOT / "tests" / "deterministic"),
        str(ROOT / "tests" / "orchestration"),
        "-q",
    ]


def main() -> int:
    return int(pytest.main(test_arguments()))


if __name__ == "__main__":
    raise SystemExit(main())
