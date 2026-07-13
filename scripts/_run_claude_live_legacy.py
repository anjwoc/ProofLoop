#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, check=False, **kwargs)


def latest_run(repo: Path) -> Path | None:
    runs = repo / ".proofloop" / "runs"
    if not runs.exists():
        return None
    items = sorted((item for item in runs.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime, reverse=True)
    return items[0] if items else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an authenticated Claude Code ProofLoop acceptance test")
    parser.add_argument("--max-budget-usd", type=float, default=8.0)
    parser.add_argument("--max-turns", type=int, default=80)
    parser.add_argument("--permission-mode", default="auto", choices=["auto", "acceptEdits", "bypassPermissions", "default"])
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--claude-bin", default="claude")
    args = parser.parse_args()

    claude = shutil.which(args.claude_bin) if os.path.sep not in args.claude_bin else args.claude_bin
    if not claude or not Path(claude).exists():
        print(json.dumps({"verdict": "BLOCKED", "reason": "CLAUDE_CLI_MISSING"}))
        return 2

    build = run([sys.executable, str(ROOT / "scripts" / "build_claude_plugin.py")], ROOT, capture_output=True)
    if build.returncode != 0:
        print(build.stderr, file=sys.stderr)
        return build.returncode
    plugin = ROOT / "dist" / "claude" / "plugins" / "proofloop"

    temp_holder = tempfile.TemporaryDirectory(prefix="proofloop-live-")
    workspace = Path(temp_holder.name)
    shutil.copytree(ROOT / "tests" / "live" / "fixtures" / "normal", workspace, dirs_exist_ok=True)
    for command in (["git", "init"], ["git", "config", "user.email", "proofloop@example.com"], ["git", "config", "user.name", "ProofLoop"], ["git", "add", "."], ["git", "commit", "-m", "baseline"]):
        completed = run(list(command), workspace, capture_output=True)
        if completed.returncode != 0:
            print(completed.stderr, file=sys.stderr)
            return completed.returncode

    prompt = (
        "Use ProofLoop to fix the concurrency bug described in README.md. "
        "Do not weaken tests or change the public API. Use the installed ProofLoop skills and named subagents. "
        "Create deterministic evidence and finish only through the truth gate."
    )
    output = workspace / "claude-stream.jsonl"
    errors = workspace / "claude-stderr.log"
    command = [
        str(claude), "-p", prompt,
        "--model", "opus",
        "--plugin-dir", str(plugin),
        "--output-format", "stream-json",
        "--verbose",
        "--include-hook-events",
        "--max-budget-usd", str(args.max_budget_usd),
        "--max-turns", str(args.max_turns),
        "--permission-mode", args.permission_mode,
    ]
    with output.open("w", encoding="utf-8") as stdout_handle, errors.open("w", encoding="utf-8") as stderr_handle:
        completed = run(command, workspace, stdout=stdout_handle, stderr=stderr_handle)

    run_dir = latest_run(workspace)
    if run_dir is None:
        result = {"verdict": "FAILED", "reason": "NO_PROOFLOOP_RUN", "claudeExitCode": completed.returncode, "workspace": str(workspace)}
    else:
        truth = run_dir / "truth-report.json"
        if not truth.exists():
            result = {"verdict": "FAILED", "reason": "TRUTH_REPORT_MISSING", "claudeExitCode": completed.returncode, "runDir": str(run_dir), "workspace": str(workspace)}
        else:
            report = json.loads(truth.read_text(encoding="utf-8"))
            result = {"verdict": report.get("verdict"), "claudeExitCode": completed.returncode, "runDir": str(run_dir), "workspace": str(workspace), "truthReport": report}
    print(json.dumps(result, indent=2))
    if args.keep_workspace:
        temp_holder.cleanup = lambda: None  # type: ignore[method-assign]
        print(f"Workspace retained: {workspace}", file=sys.stderr)
    else:
        temp_holder.cleanup()
    return 0 if result.get("verdict") == "PROVEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
