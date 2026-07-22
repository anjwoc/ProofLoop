#!/usr/bin/env python3
"""Verify that a run delivers the observable product contract.

This is deliberately separate from the Truth Engine: it checks whether the
user could inspect how a run was interpreted and proven, while Truth decides
whether the requested repository change is actually proven.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proofloop_core.contracts.expected_output import write_expected_output_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a ProofLoop run against docs/roadmap/expected-output.md")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--repository", type=Path, help="Repository that the host skill was asked to operate in")
    parser.add_argument("--require-terminal", action="store_true", help="Require final checks, evidence, and Truth verdict")
    args = parser.parse_args()
    report = write_expected_output_report(
        args.run_dir,
        expected_repository=args.repository,
        require_terminal=args.require_terminal,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"PASS", "IN_PROGRESS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
