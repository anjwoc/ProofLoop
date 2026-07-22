#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from proofloop_core.contracts.expected_output import write_expected_output_report
from proofloop_core.context.io import read_json


AGY_MODEL_LABELS = {
    "gemini-3.5-flash-medium": "Gemini 3.5 Flash (Medium)",
    "gemini-3.5-flash-high": "Gemini 3.5 Flash (High)",
    "gemini-3.5-flash-low": "Gemini 3.5 Flash (Low)",
    "gemini-3.1-pro-low": "Gemini 3.1 Pro (Low)",
    "gemini-3.1-pro-high": "Gemini 3.1 Pro (High)",
}


def run(command: list[str], cwd: Path, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, check=False, **kwargs)


def latest_run(repo: Path) -> Path | None:
    runs = repo / ".proofloop" / "runs"
    if not runs.exists():
        return None
    items = sorted((item for item in runs.iterdir() if item.is_dir()), key=lambda item: item.stat().st_mtime, reverse=True)
    return items[0] if items else None


def init_workspace(scenario: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    holder = tempfile.TemporaryDirectory(prefix=f"proofloop-{scenario}-live-")
    # The temporary holder owns harness-only artifacts; the repository itself
    # lives one level below it.  Host stream logs must never appear as a dirty
    # source change inside the fixture that ProofLoop is evaluating.
    workspace = Path(holder.name) / "workspace"
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


def host_transcript_dir(workspace: Path) -> Path:
    directory = workspace.parent / "host-transcripts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def wait_for_background_relays(workspace: Path, timeout_seconds: int, *, poll_seconds: float = 2.0) -> None:
    """Wait for a host skill's detached parent run, if it launched one.

    All three packaged entry skills use the same relay protocol. The external
    host may finish its coordinator turn before that detached run completes,
    so live acceptance must wait for the run rather than misreporting a missing
    Truth artifact. This is a harness concern only; it never writes inside the
    fixture repository.
    """
    relay_dirs = sorted((workspace / ".proofloop" / "relay").glob("*"))
    pids: list[int] = []
    for relay_dir in relay_dirs:
        pid_file = relay_dir / "pid"
        if not pid_file.is_file():
            continue
        try:
            pids.append(int(pid_file.read_text(encoding="utf-8").strip()))
        except ValueError:
            continue
    if not pids:
        return
    print(f"Waiting for ProofLoop background process(es) {', '.join(str(pid) for pid in pids)} to finish...", file=sys.stderr)
    deadline = time.monotonic() + timeout_seconds
    pending = set(pids)
    while pending and time.monotonic() < deadline:
        for pid in list(pending):
            # A test harness can be the direct parent of a relay. Reap a
            # finished child so its zombie PID is not mistaken for a live
            # detached process. Real host relays are usually not children of
            # this process, in which case waitpid raises ChildProcessError.
            try:
                reaped, _status = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                reaped = 0
            if reaped == pid:
                pending.remove(pid)
                continue
            try:
                os.kill(pid, 0)
            except OSError:
                pending.remove(pid)
        if pending:
            time.sleep(poll_seconds)


def _build_adapter(host: str, output: Path) -> None:
    completed = run(
        [sys.executable, str(ROOT / "scripts" / "build_host_adapter.py"), "--host", host, "--output", str(output)],
        ROOT,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)


def setup_claude_project(workspace: Path) -> Path:
    output = workspace / ".proofloop-adapter" / "claude"
    _build_adapter("claude-code", output)
    plugin = output / "plugins" / "proofloop"
    if not plugin.is_dir():
        raise RuntimeError(f"Claude Code ProofLoop plugin missing: {plugin}")
    return plugin


def setup_codex_project(workspace: Path) -> None:
    output = workspace / ".proofloop-adapter" / "codex"
    _build_adapter("codex", output)
    shutil.copytree(output / "plugins" / "proofloop" / "skills", workspace / ".agents" / "skills", dirs_exist_ok=True)
    shutil.copytree(output / "agents", workspace / ".codex" / "agents", dirs_exist_ok=True)
    shutil.copytree(output / "plugins" / "proofloop" / "hooks", workspace / ".codex" / "hooks", dirs_exist_ok=True)
    hooks_source = output / "plugins" / "proofloop" / "hooks" / "hooks.json"
    if hooks_source.exists():
        shutil.copy2(hooks_source, workspace / ".codex" / "hooks.json")


def setup_agy_project(workspace: Path) -> None:
    output = workspace / ".proofloop-adapter" / "agy"
    _build_adapter("agy", output)
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


def _host_start_failure(host: str, transcript_dir: Path, exit_code: int) -> dict[str, object]:
    """Classify a host failure that occurred before the skill could start.

    This is authenticated evidence about the host environment, not a failed
    ProofLoop run.  Keeping the distinction prevents a missing run directory
    from hiding an actionable model/auth/quota problem behind a generic error.
    """
    stream = transcript_dir / f"{host}-stream.jsonl"
    stderr = transcript_dir / f"{host}-stderr.log"
    text = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (stream, stderr)
        if path.is_file()
    )
    lowered = text.lower()
    verdict = "BLOCKED"
    if exit_code == 0:
        verdict = "FAILED"
        reason = "NO_PROOFLOOP_RUN"
    elif "not supported" in lowered or "requires a newer version" in lowered or "model_not_found" in lowered:
        reason = "HOST_MODEL_UNAVAILABLE"
    elif "rate limit" in lowered or "hit your limit" in lowered or "status\":429" in lowered:
        reason = "HOST_RATE_LIMITED"
    elif "not authenticated" in lowered or "login" in lowered or "authentication" in lowered:
        reason = "HOST_AUTH_REQUIRED"
    else:
        reason = "HOST_START_FAILED"
    message = next((line.strip() for line in reversed(text.splitlines()) if line.strip()), None)
    return {
        "verdict": verdict,
        "reason": reason,
        "hostMessage": message,
        "hostExitCode": exit_code,
        "transcriptDir": str(transcript_dir),
    }


def result_from_workspace(host: str, scenario: str, workspace: Path, exit_code: int, transcript_dir: Path) -> dict[str, object]:
    run_dir = latest_run(workspace)
    if run_dir is None:
        return {
            **_host_start_failure(host, transcript_dir, exit_code),
            "workspace": str(workspace),
            "scenario": scenario,
        }
    truth = run_dir / "truth-report.json"
    if not truth.exists():
        return {"verdict": "FAILED", "reason": "TRUTH_REPORT_MISSING", "hostExitCode": exit_code, "runDir": str(run_dir), "workspace": str(workspace), "scenario": scenario}
    report = read_json(truth)
    if not isinstance(report, dict):
        return {"verdict": "FAILED", "reason": "TRUTH_REPORT_INVALID", "hostExitCode": exit_code, "runDir": str(run_dir), "workspace": str(workspace), "scenario": scenario}
    run_metadata = read_json(run_dir / "run.json")
    actual_host = run_metadata.get("host") if isinstance(run_metadata, dict) else None
    if actual_host != host:
        return {
            "verdict": "BLOCKED",
            "reason": "HOST_SKILL_ROUTING_MISMATCH",
            "expectedHost": host,
            "actualHost": actual_host,
            "hostExitCode": exit_code,
            "runDir": str(run_dir),
            "workspace": str(workspace),
            "scenario": scenario,
            "truthReport": report,
        }
    roles = _roles(run_dir)
    recovery_observed = "implementer_recovery" in roles
    verdict = report.get("verdict")
    reason = None
    if scenario == "recovery" and verdict == "PROVEN" and not recovery_observed:
        verdict = "UNPROVEN"
        reason = "RECOVERY_NOT_OBSERVED"
    experience = write_expected_output_report(
        run_dir,
        expected_repository=workspace,
        require_terminal=True,
    )
    if experience["status"] != "PASS":
        verdict = "UNPROVEN"
        reason = "EXPECTED_OUTPUT_CONTRACT_FAILED"
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
        "expectedOutput": experience,
    }


def save_acceptance_report(host: str, scenario: str, result: dict[str, object]) -> Path | None:
    """Retain every authenticated attempt, including a host-side failure.

    A missing ProofLoop run is the most important live-harness diagnostic. The
    previous implementation discarded the only host transcript in that case,
    leaving a release gate with a bare "MISSING" result and no repairable
    evidence. Successful runs preserve the existing release-gate layout;
    unsuccessful runs retain the workspace transcript under an attempt report
    without pretending to have produced a truth report.
    """
    run_value = result.get("runDir")
    destination = ROOT / "reports" / "live" / f"{host}-{scenario}"
    if destination.exists():
        shutil.rmtree(destination)
    source = Path(run_value) if isinstance(run_value, str) else None
    run_available = source is not None and source.is_dir()
    successful_run = run_available and source is not None and (source / "truth-report.json").is_file()
    if source is not None and source.is_dir():
        shutil.copytree(source, destination)
    else:
        destination.mkdir(parents=True, exist_ok=True)
        transcript_value = result.get("transcriptDir") or result.get("workspace")
        transcript_dir = Path(transcript_value) if isinstance(transcript_value, str) else None
        if transcript_dir is not None and transcript_dir.is_dir():
            for filename in (f"{host}-stream.jsonl", f"{host}-stderr.log"):
                artifact = transcript_dir / filename
                if artifact.is_file():
                    shutil.copy2(artifact, destination / filename)
    original = destination / "truth-report.json"
    if successful_run and original.exists():
        shutil.copy2(original, destination / "orchestrator-truth-report.json")
    truth_report = result.get("truthReport")
    expected_output = result.get("expectedOutput")
    acceptance = {
        "schemaVersion": "1.0",
        "verdict": result.get("verdict"),
        "reason": result.get("reason"),
        "host": host,
        "scenario": scenario,
        "hostExitCode": result.get("hostExitCode"),
        "roles": result.get("roles", []),
        "recoveryObserved": result.get("recoveryObserved", False),
        "orchestratorTruthVerdict": truth_report.get("verdict") if isinstance(truth_report, dict) else None,
        "expectedOutputStatus": expected_output.get("status") if isinstance(expected_output, dict) else None,
        "expectedOutputFailures": expected_output.get("failures") if isinstance(expected_output, dict) else [],
        "source": "AUTHENTICATED_HOST_RUN",
    }
    target = original if successful_run else destination / "acceptance-attempt.json"
    target.write_text(json.dumps(acceptance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an authenticated ProofLoop acceptance test on Claude Code, Codex, or AGY")
    parser.add_argument("--host", choices=["claude-code", "codex", "agy", "antigravity"], required=True)
    parser.add_argument("--scenario", choices=["normal", "recovery"], default="normal")
    parser.add_argument("--binary")
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--no-save-report", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--codex-model",
        help="Optional Codex model. Omit to use the authenticated account default and record that fact.",
    )
    parser.add_argument("--agy-model", default="gemini-3.5-flash-medium")
    parser.add_argument("--claude-model", default="opus")
    args = parser.parse_args()

    if args.host == "antigravity":
        args.host = "agy"
    default_binary = {"claude-code": "claude", "codex": "codex", "agy": "agy"}[args.host]
    binary_value = args.binary or default_binary
    executable = shutil.which(binary_value) if os.path.sep not in binary_value else binary_value
    if not executable or not Path(executable).exists():
        print(json.dumps({"verdict": "BLOCKED", "reason": f"{args.host.upper()}_CLI_MISSING"}))
        return 2
    holder, workspace = init_workspace(args.scenario)
    transcript_dir = host_transcript_dir(workspace)
    output = transcript_dir / f"{args.host}-stream.jsonl"
    errors = transcript_dir / f"{args.host}-stderr.log"
    prompt = (
        "Invoke the installed proofloop skill for this exact request: "
        + (workspace / "README.md").read_text(encoding="utf-8")
        + " Do not simulate ProofLoop states and do not call internal invoke-role or record-attempt commands manually. "
        "The skill must launch proofloop-core run --mode adaptive and report the resulting truth verdict exactly."
    )
    if args.host == "claude-code":
        plugin = setup_claude_project(workspace)
        command = [
            str(executable), "--plugin-dir", str(plugin), "-p", prompt,
            "--model", args.claude_model,
            "--output-format", "stream-json", "--include-partial-messages", "--verbose",
            "--permission-mode", "bypassPermissions",
        ]
    elif args.host == "codex":
        setup_codex_project(workspace)
        command = [
            str(executable), "exec", "--json", "--ephemeral", "--sandbox", "workspace-write",
            # The harness validates the packaged, project-local skill. It
            # must retain the authenticated account but not inherit an
            # unrelated global model override or malformed global agents.
            "--ignore-user-config",
            "--dangerously-bypass-hook-trust",
        ]
        if args.codex_model:
            command.extend(["--model", args.codex_model])
        command.append(prompt)
    else:
        setup_agy_project(workspace)
        command = [
            str(executable),
            "--dangerously-skip-permissions",
            "--prompt",
            prompt,
            "--model",
            AGY_MODEL_LABELS.get(args.agy_model, args.agy_model),
        ]
    try:
        with output.open("w", encoding="utf-8") as stdout_handle, errors.open("w", encoding="utf-8") as stderr_handle:
            environment = dict(os.environ)
            if args.host == "codex":
                environment["PROOFLOOP_CODEX_MODEL"] = args.codex_model or "CURRENT_ACCOUNT_DEFAULT"
            elif args.host == "agy":
                # The installed AGY entry skill propagates this to its
                # detached ProofLoop child. Mirror that contract in the live
                # harness so an authenticated host run has the same
                # non-interactive permission mode as a user invocation.
                environment["PROOFLOOP_AGY_BYPASS_PERMISSIONS"] = "1"
            completed = subprocess.run(
                command,
                cwd=workspace,
                text=True,
                stdout=stdout_handle,
                stderr=stderr_handle,
                timeout=args.timeout_seconds,
                check=False,
                env=environment,
            )

        wait_for_background_relays(workspace, args.timeout_seconds)

        result = result_from_workspace(args.host, args.scenario, workspace, completed.returncode, transcript_dir)
        result["hostCommand"] = command[:-1]
    except subprocess.TimeoutExpired:
        result = {"verdict": "BLOCKED", "reason": "HOST_TIMEOUT", "workspace": str(workspace), "scenario": args.scenario}
    result["transcriptDir"] = str(transcript_dir)
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
