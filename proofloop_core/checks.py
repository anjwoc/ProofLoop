from __future__ import annotations

import os
import re
import time
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from .events import EventEmitter
from .io import sha256_file, write_json
from .process_runner import ProcessRunner
from .task_brief import CheckSpec, SurfaceScenario, TaskBrief


def _safe_name(index: int, name: str | None) -> str:
    raw = name or f"check-{index:02d}"
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw).strip("-") or f"check-{index:02d}"


def run_checks(
    task: TaskBrief,
    repository: str | Path,
    output_dir: str | Path,
    *,
    emitter: EventEmitter | None = None,
    phase: str = "VERIFY",
) -> dict[str, Any]:
    repo = Path(repository).resolve()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    for index, check in enumerate(task.required_checks, start=1):
        name = _safe_name(index, check.name)
        stdout_path = output / f"{index:02d}-{name}.stdout.log"
        stderr_path = output / f"{index:02d}-{name}.stderr.log"
        cwd = (repo / check.cwd).resolve() if check.cwd else repo
        if repo not in cwd.parents and cwd != repo:
            raise ValueError(f"check cwd escapes repository: {cwd}")
        command_id = f"check-{index:03d}"
        output_tail: deque[str] = deque(maxlen=20)
        failed_tests: deque[str] = deque(maxlen=20)
        if emitter is not None:
            emitter.emit(
                "check.started",
                phase=phase,
                message=f"Check {check.name or name} started.",
                task_id=task.task_id,
                data={
                    "commandId": command_id,
                    "name": check.name or name,
                    "command": check.command,
                    "cwd": str(cwd),
                },
            )
        started = time.time()

        def on_line(stream_name: str, line: str) -> None:
            for output_line in line.splitlines():
                stripped = str(output_line).strip()
                if not stripped:
                    continue
                output_tail.append(stripped)
                if re.search(r"(?:^|\s)(?:FAIL|FAILED|ERROR)(?:\s|:|$)", stripped, re.IGNORECASE):
                    failed_tests.append(stripped)
            if emitter is None:
                return
            emitter.emit(
                "check.output",
                phase=phase,
                message=f"Check {check.name or name} produced {stream_name} output.",
                level="debug",
                task_id=task.task_id,
                data={
                    "commandId": command_id,
                    "stream": stream_name,
                    "text": line,
                },
            )

        process_result = ProcessRunner().run(
            check.command,
            cwd=cwd,
            env={**os.environ, "PROOFLOOP_TASK_ID": task.task_id},
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            timeout_seconds=check.timeout_seconds,
            on_line=on_line,
        )
        if process_result.timed_out:
            with stderr_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\nProofLoop timeout after {check.timeout_seconds}s\n")
                handle.flush()
        finished = time.time()
        status = "PASS" if process_result.exit_code == 0 else "FAIL"
        result: dict[str, Any] = {
            "name": check.name or name,
            "command": check.command,
            "cwd": str(cwd),
            "exitCode": process_result.exit_code,
            "timedOut": process_result.timed_out,
            "startedAtEpoch": started,
            "finishedAtEpoch": finished,
            "durationSeconds": round(finished - started, 6),
            "stdoutRef": str(stdout_path),
            "stderrRef": str(stderr_path),
            "stdoutSha256": sha256_file(stdout_path),
            "stderrSha256": sha256_file(stderr_path),
            "status": status,
        }
        results.append(result)
        if emitter is not None:
            event_type = "check.completed" if process_result.exit_code == 0 else "check.failed"
            failure_reason = None
            if process_result.timed_out:
                failure_reason = f"timeout after {check.timeout_seconds}s"
            elif process_result.cancelled:
                failure_reason = "check cancelled"
            elif process_result.exit_code != 0:
                failure_reason = f"command exited with {process_result.exit_code}"
            emitter.emit(
                event_type,
                phase=phase,
                message=f"Check {check.name or name} {status.lower()}.",
                level="info" if process_result.exit_code == 0 else "error",
                task_id=task.task_id,
                data={
                    "commandId": command_id,
                    "name": check.name or name,
                    "command": check.command,
                    "cwd": str(cwd),
                    "exitCode": process_result.exit_code,
                    "timedOut": process_result.timed_out,
                    "durationSeconds": result["durationSeconds"],
                    "stdoutRef": str(stdout_path),
                    "stderrRef": str(stderr_path),
                    "failedTests": [] if process_result.exit_code == 0 else list(failed_tests),
                    "outputTail": [] if process_result.exit_code == 0 else list(output_tail),
                    "failureReason": failure_reason,
                },
            )

    verdict = "PASS" if all(item["exitCode"] == 0 for item in results) else "FAIL"
    report = {
        "schemaVersion": "1.0",
        "taskId": task.task_id,
        "repository": str(repo),
        "verdict": verdict,
        "checks": results,
    }
    write_json(output / "checks.json", report)
    return report


# Structured proof plans deliberately reuse the parent-owned direct-argv check
# runner above. They are not model assertions and cannot be marked pass by an
# agent response.
POST_IMPLEMENTATION_PROOF_STAGES = ("automated", "surface", "adversarial", "cleanup")


def proof_stage_checks(task: TaskBrief, stage: str) -> tuple[CheckSpec, ...]:
    plan = task.proof_plan
    if plan is None:
        return ()
    checks_by_stage = {
        "baseline": plan.baseline_checks,
        "red": plan.red_checks,
        "automated": plan.automated_checks,
        "adversarial": plan.adversarial_checks,
        "cleanup": plan.cleanup_checks,
        "surface": tuple(_surface_check(scenario) for scenario in plan.surface_scenarios),
    }
    if stage not in checks_by_stage:
        raise ValueError(f"unknown proof stage: {stage}")
    return checks_by_stage[stage]


def run_proof_stage(
    task: TaskBrief,
    stage: str,
    repository: str | Path,
    output_dir: str | Path,
    *,
    emitter: EventEmitter | None = None,
    phase: str = "VERIFY",
) -> dict[str, Any]:
    """Run one proof stage and report whether its expected outcome occurred."""
    checks = proof_stage_checks(task, stage)
    destination = Path(output_dir)
    if not checks:
        report: dict[str, Any] = {
            "schemaVersion": "1.0", "taskId": task.task_id, "proofStage": stage,
            "expectedOutcome": "FAIL" if stage == "red" else "PASS", "verdict": "SKIPPED",
            "checks": [], "expectationMet": True,
        }
        destination.mkdir(parents=True, exist_ok=True)
        write_json(destination / "proof-stage.json", report)
        return report

    report = run_checks(replace(task, required_checks=checks), repository, destination, emitter=emitter, phase=phase)
    statuses = [str(item.get("status")) for item in report.get("checks", []) if isinstance(item, dict)]
    expected = "FAIL" if stage == "red" else "PASS"
    wrapped = {
        **report,
        "proofStage": stage,
        "expectedOutcome": expected,
        "expectationMet": bool(statuses) and all(status == expected for status in statuses),
    }
    write_json(destination / "proof-stage.json", wrapped)
    return wrapped


def run_post_implementation_proof(
    task: TaskBrief,
    repository: str | Path,
    output_dir: str | Path,
    *,
    emitter: EventEmitter | None = None,
    phase: str = "VERIFY",
) -> dict[str, Any]:
    root = Path(output_dir)
    reports = [
        run_proof_stage(task, stage, repository, root / stage, emitter=emitter, phase=phase)
        for stage in POST_IMPLEMENTATION_PROOF_STAGES
    ]
    merged = merge_check_reports(task.task_id, reports)
    merged["proofStages"] = [
        {
            "stage": report["proofStage"], "verdict": report["verdict"],
            "expectationMet": report["expectationMet"],
            "reportRef": str(root / report["proofStage"] / "proof-stage.json"),
        }
        for report in reports
    ]
    write_json(root / "post-proof.json", merged)
    return merged


def merge_check_reports(task_id: str, reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    report_list = list(reports)
    checks: list[dict[str, Any]] = []
    for report in report_list:
        raw_checks = report.get("checks")
        if isinstance(raw_checks, list):
            checks.extend(check for check in raw_checks if isinstance(check, dict))
    expectation_met = all(report.get("expectationMet", True) for report in report_list)
    return {
        "schemaVersion": "1.0", "taskId": task_id,
        "verdict": "PASS" if expectation_met and all(check.get("status") == "PASS" for check in checks) else "FAIL",
        "checks": checks,
    }


def merge_required_and_post_proof(
    task_id: str, required_checks: dict[str, Any], post_proof: dict[str, Any]
) -> dict[str, Any]:
    checks = [
        *[item for item in required_checks.get("checks", []) if isinstance(item, dict)],
        *[item for item in post_proof.get("checks", []) if isinstance(item, dict)],
    ]
    return {
        "schemaVersion": "1.0", "taskId": task_id,
        "verdict": "PASS" if required_checks.get("verdict") == "PASS" and post_proof.get("verdict") == "PASS" else "FAIL",
        "checks": checks,
    }


def _surface_check(scenario: SurfaceScenario) -> CheckSpec:
    return CheckSpec(
        command=list(scenario.command), cwd=scenario.cwd,
        timeout_seconds=scenario.timeout_seconds, name=f"surface-{scenario.scenario_id}",
    )
