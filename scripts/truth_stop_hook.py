#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
for candidate in (PLUGIN_ROOT, Path.home() / ".proofloop" / "runtime"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from proofloop_core.run_state import load_active_run


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--host", choices=["claude-code", "codex"], default="codex")
    args, _ = parser.parse_known_args()
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
