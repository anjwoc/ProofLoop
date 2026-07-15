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
sys.path.insert(0, str(ROOT))


def run(command: list[str], cwd: Path, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, check=False, **kwargs)


def latest_run(repo: Path) -> Path | None:
    runs = repo / ".proofloop" / "runs"
    if not runs.exists():
        return None
    items = sorted((item for item in runs.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime, reverse=True)
    return items[0] if items else None


def init_workspace(scenario: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    holder = tempfile.TemporaryDirectory(prefix=f"proofloop-{scenario}-live-")
    workspace = Path(holder.name)
    fixture = ROOT / "tests" / "live" / "fixtures" / scenario
    if not fixture.exists():
        holder.cleanup()
        raise FileNotFoundError(fixture)
    shutil.copytree(fixture, workspace, dirs_exist_ok=True)
    for command in (["git", "init"], ["git", "config", "user.email", "proofloop@example.com"], ["git", "config", "user.name", "ProofLoop"], ["git", "add", "."], ["git", "commit", "-m", "baseline"]):
        completed = run(list(command), workspace, capture_output=True)
        if completed.returncode != 0:
            holder.cleanup()
            raise RuntimeError(completed.stderr)
    return holder, workspace


def _build_adapter(host: str, output: Path) -> None:
    completed = run(
        [sys.executable, str(ROOT / "scripts" / "build_host_adapter.py"), "--host", host, "--output", str(output)],
        ROOT,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)


def setup_codex_project(workspace: Path) -> None:
    output = workspace / ".proofloop-adapter" / "codex"
    _build_adapter("codex", output)
    shutil.copytree(output / "plugins" / "proofloop" / "skills", workspace / ".agents" / "skills", dirs_exist_ok=True)
    shutil.copytree(output / "agents", workspace / ".codex" / "agents", dirs_exist_ok=True)
    shutil.copytree(output / "plugins" / "proofloop" / "hooks", workspace / ".codex" / "hooks", dirs_exist_ok=True)
    hooks_source = output / "plugins" / "proofloop" / "hooks" / "hooks.json"
    if hooks_source.exists():
        shutil.copy2(hooks_source, workspace / ".codex" / "hooks.json")


def setup_antigravity_project(workspace: Path) -> None:
    output = workspace / ".proofloop-adapter" / "antigravity"
    _build_adapter("antigravity", output)
    shutil.copytree(output / "skills", workspace / ".agents" / "skills", dirs_exist_ok=True)
    workflow_dir = workspace / ".agent" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output / "workflows" / "proofloop.md", workflow_dir / "proofloop.md")


def _roles(run_dir: Path) -> list[str]:
    path = run_dir / "invocations.jsonl"
    if not path.exists():
        return []
    roles: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            role = json.loads(line).get("role")
        except json.JSONDecodeError:
            continue
        if isinstance(role, str):
            roles.append(role)
    return roles


def result_from_workspace(host: str, scenario: str, workspace: Path, exit_code: int) -> dict[str, object]:
    run_dir = latest_run(workspace)
    if run_dir is None:
        return {"verdict": "FAILED", "reason": "NO_PROOFLOOP_RUN", "hostExitCode": exit_code, "workspace": str(workspace), "scenario": scenario}
    truth = run_dir / "truth-report.json"
    if not truth.exists():
        return {"verdict": "FAILED", "reason": "TRUTH_REPORT_MISSING", "hostExitCode": exit_code, "runDir": str(run_dir), "workspace": str(workspace), "scenario": scenario}
    report = json.loads(truth.read_text(encoding="utf-8"))
    roles = _roles(run_dir)
    recovery_observed = "implementer_recovery" in roles
    verdict = report.get("verdict")
    reason = None
    if scenario == "recovery" and verdict == "PROVEN" and not recovery_observed:
        verdict = "UNPROVEN"
        reason = "RECOVERY_NOT_OBSERVED"
    return {
        "verdict": verdict,
        "reason": reason,
        "scenario": scenario,
        "hostExitCode": exit_code,
        "runDir": str(run_dir),
        "workspace": str(workspace),
        "roles": roles,
        "recoveryObserved": recovery_observed,
        "truthReport": report,
    }


def save_acceptance_report(host: str, scenario: str, result: dict[str, object]) -> Path | None:
    run_value = result.get("runDir")
    if not isinstance(run_value, str):
        return None
    source = Path(run_value)
    if not source.exists():
        return None
    destination = ROOT / "reports" / "live" / f"{host}-{scenario}"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    original = destination / "truth-report.json"
    if original.exists():
        shutil.copy2(original, destination / "orchestrator-truth-report.json")
    acceptance = {
        "schemaVersion": "1.0",
        "verdict": result.get("verdict"),
        "reason": result.get("reason"),
        "host": host,
        "scenario": scenario,
        "hostExitCode": result.get("hostExitCode"),
        "roles": result.get("roles", []),
        "recoveryObserved": result.get("recoveryObserved", False),
        "orchestratorTruthVerdict": (result.get("truthReport") or {}).get("verdict") if isinstance(result.get("truthReport"), dict) else None,
        "source": "AUTHENTICATED_HOST_RUN",
    }
    original.write_text(json.dumps(acceptance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an authenticated ProofLoop acceptance test on Codex or Antigravity")
    parser.add_argument("--host", choices=["codex", "antigravity"], required=True)
    parser.add_argument("--scenario", choices=["normal", "recovery"], default="normal")
    parser.add_argument("--binary")
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--no-save-report", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--antigravity-model", default="Gemini 3.1 Pro (High)")
    args = parser.parse_args()
    default_binary = "codex" if args.host == "codex" else "agy"
    binary_value = args.binary or default_binary
    executable = shutil.which(binary_value) if os.path.sep not in binary_value else binary_value
    if not executable or not Path(executable).exists():
        print(json.dumps({"verdict": "BLOCKED", "reason": f"{args.host.upper()}_CLI_MISSING"}))
        return 2
    holder, workspace = init_workspace(args.scenario)
    output = workspace / f"{args.host}-stream.jsonl"
    errors = workspace / f"{args.host}-stderr.log"
    prompt = (
        "Invoke the installed proofloop skill for this exact request: "
        + (workspace / "README.md").read_text(encoding="utf-8")
        + " Do not simulate ProofLoop states and do not call internal invoke-role or record-attempt commands manually. "
        "The skill must launch proofloop-core goal and report the resulting truth verdict exactly."
    )
    if args.host == "codex":
        setup_codex_project(workspace)
        command = [
            str(executable), "exec", "--json", "--ephemeral", "--sandbox", "workspace-write",
            "--dangerously-bypass-hook-trust", "--model", "gpt-5.6", prompt,
        ]
    else:
        setup_antigravity_project(workspace)
        command = [str(executable), "--model", args.antigravity_model]
        if os.environ.get("PROOFLOOP_ANTIGRAVITY_BYPASS_PERMISSIONS") == "1":
            command.append("--dangerously-skip-permissions")
        command.extend(["-p", prompt])
    try:
        with output.open("w", encoding="utf-8") as stdout_handle, errors.open("w", encoding="utf-8") as stderr_handle:
            completed = subprocess.run(command, cwd=workspace, text=True, stdout=stdout_handle, stderr=stderr_handle, timeout=args.timeout_seconds, check=False)
        result = result_from_workspace(args.host, args.scenario, workspace, completed.returncode)
    except subprocess.TimeoutExpired:
        result = {"verdict": "BLOCKED", "reason": "HOST_TIMEOUT", "workspace": str(workspace), "scenario": args.scenario}
    if not args.no_save_report:
        saved = save_acceptance_report(args.host, args.scenario, result)
        if saved:
            result["savedReport"] = str(saved)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.keep_workspace:
        holder.cleanup = lambda: None  # type: ignore[method-assign]
        print(f"Workspace retained: {workspace}", file=sys.stderr)
    else:
        holder.cleanup()
    return 0 if result.get("verdict") == "PROVEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
