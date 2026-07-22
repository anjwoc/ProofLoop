#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
for candidate in (Path.home() / ".proofloop" / "runtime", PLUGIN_ROOT):
    if str(candidate) in sys.path:
        sys.path.remove(str(candidate))
    sys.path.insert(0, str(candidate))

from proofloop_core.contracts.run_state import load_active_run


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", choices=["claude-code", "codex"], default="codex")
    args, _ = parser.parse_known_args()
    # A nested role cannot create truth-report.json; only the parent
    # orchestrator can. Blocking it here creates a self-loop after a valid
    # planner/reviewer result has already been returned.
    if os.environ.get("PROOFLOOP_ROLE_CHILD") == "1":
        if args.host == "codex":
            print("{}")
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if payload.get("stop_hook_active"):
        if args.host == "codex":
            print("{}")
        return 0
    active = load_active_run(payload.get("cwd", "."))
    if not active:
        if args.host == "codex":
            print("{}")
        return 0
    run_dir = Path(active["runDir"])
    truth = run_dir / "truth-report.json"
    if truth.exists():
        if args.host == "codex":
            print("{}")
        return 0
    sys.stderr.write(
        "[ProofLoop] Active run has no truth-report.json. Continue the workflow, run "
        "$HOME/.proofloop/bin/proofloop-core verify-run, or explicitly abort the run.\n"
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
