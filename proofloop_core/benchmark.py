from __future__ import annotations

import io
import json
import os
import random
import shutil
import statistics
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .host_runner import invoke_role
from .io import write_json
from .orchestrator import converge_goal
from .run_state import start_run
from .tokscale import TokScaleAdapter
from .usage import build_usage_summary


ROLES = ("planner_deep", "explorer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep")


def load_benchmark_suite(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("tasks"), list) or not value["tasks"]:
        raise ValueError("benchmark suite must contain a non-empty tasks array")
    for task in value["tasks"]:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not isinstance(task.get("request"), str):
            raise ValueError("each benchmark task requires string id and request")
        checks = task.get("checks", [])
        if not isinstance(checks, list) or any(
            not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command)
            for command in checks
        ):
            raise ValueError("benchmark task checks must be arrays of command arguments")
    return value


def run_benchmark(
    suite_path: str | Path,
    repository: str | Path,
    *,
    mode: str,
    repetitions: int,
    baseline_host: str,
    baseline_model: str,
    proofloop_host: str,
    timeout_seconds: int = 1200,
    seed: int = 0,
) -> dict[str, Any]:
    if mode not in {"routing", "system", "both"}:
        raise ValueError("unsupported benchmark mode")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    repo = Path(repository).resolve()
    suite = load_benchmark_suite(suite_path)
    baseline = _git(repo, "rev-parse", "HEAD").stdout.strip()
    benchmark_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    root = repo / ".proofloop" / "benchmarks" / benchmark_id
    root.mkdir(parents=True, exist_ok=False)
    modes = ("routing", "system") if mode == "both" else (mode,)
    manifest = {
        "schemaVersion": "1.0",
        "benchmarkId": benchmark_id,
        "suite": str(Path(suite_path).resolve()),
        "repository": str(repo),
        "baselineCommit": baseline,
        "modes": list(modes),
        "repetitions": repetitions,
        "baselineHost": baseline_host,
        "baselineModel": baseline_model,
        "proofloopHost": proofloop_host,
        "seed": seed,
    }
    write_json(root / "manifest.json", manifest)
    schedule: list[tuple[str, int, dict[str, Any], str]] = []
    rng = random.Random(seed)
    for selected_mode in modes:
        for repetition in range(1, repetitions + 1):
            for task in suite["tasks"]:
                arms = [f"baseline-{selected_mode}", f"proofloop-{selected_mode}"]
                rng.shuffle(arms)
                schedule.extend((selected_mode, repetition, task, arm) for arm in arms)

    trials: list[dict[str, Any]] = []
    trials_path = root / "trials.jsonl"
    for order, (selected_mode, repetition, task, arm) in enumerate(schedule, start=1):
        trial_id = f"trial-{order:04d}-{task['id']}-{arm}"
        with _isolated_worktree(repo, baseline) as worktree:
            trial = _execute_trial(
                worktree,
                task,
                arm=arm,
                selected_mode=selected_mode,
                baseline_host=baseline_host,
                baseline_model=baseline_model,
                proofloop_host=proofloop_host,
                timeout_seconds=timeout_seconds,
            )
            trial.update(
                {
                    "schemaVersion": "1.0",
                    "trialId": trial_id,
                    "taskId": task["id"],
                    "mode": selected_mode,
                    "arm": arm,
                    "repetition": repetition,
                    "order": order,
                }
            )
            _copy_trial_artifacts(trial, root / "trials" / trial_id)
        trials.append(trial)
        with trials_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(trial, ensure_ascii=False, separators=(",", ":")) + "\n")

    comparison = compare_trials(trials)
    write_json(root / "comparison.json", comparison)
    return {"benchmarkId": benchmark_id, "benchmarkDir": str(root), "comparison": comparison}


def compare_benchmark(benchmark_dir: str | Path) -> dict[str, Any]:
    root = Path(benchmark_dir)
    trials = [
        json.loads(line)
        for line in (root / "trials.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    result = compare_trials(trials)
    write_json(root / "comparison.json", result)
    return result


def compare_trials(trials: list[dict[str, Any]]) -> dict[str, Any]:
    modes = sorted({str(item["mode"]) for item in trials})
    comparisons = []
    for mode in modes:
        baseline = [item for item in trials if item["mode"] == mode and item["arm"] == f"baseline-{mode}"]
        candidate = [item for item in trials if item["mode"] == mode and item["arm"] == f"proofloop-{mode}"]
        baseline_metrics = _arm_metrics(baseline)
        candidate_metrics = _arm_metrics(candidate)
        token_gain = _gain(baseline_metrics.get("tokensPerProven"), candidate_metrics.get("tokensPerProven"))
        cost_gain = _gain(baseline_metrics.get("costPerProven"), candidate_metrics.get("costPerProven"))
        paired = _paired_token_gains(baseline, candidate)
        interval = _bootstrap_interval(paired) if len(paired) >= 2 else None
        status = "INSUFFICIENT_DATA"
        if token_gain is not None and interval is not None:
            status = (
                "IMPROVED"
                if token_gain > 0
                and interval[0] > 0
                and candidate_metrics["successRate"] >= baseline_metrics["successRate"]
                else "NO_PROVEN_GAIN"
            )
        comparisons.append(
            {
                "mode": mode,
                "status": status,
                "baseline": baseline_metrics,
                "proofloop": candidate_metrics,
                "tokenEfficiencyGainPct": token_gain,
                "costEfficiencyGainPct": cost_gain,
                "pairedTokenGain95CI": interval,
                "comparablePairs": len(paired),
            }
        )
    return {"schemaVersion": "1.0", "comparisons": comparisons}


def _execute_trial(
    repo: Path,
    task: dict[str, Any],
    *,
    arm: str,
    selected_mode: str,
    baseline_host: str,
    baseline_model: str,
    proofloop_host: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = time.monotonic()
    if arm == "baseline-system":
        result = _run_single_agent(repo, task, baseline_host, baseline_model, timeout_seconds)
    else:
        override = _single_model_routes(baseline_host, baseline_model) if arm == "baseline-routing" else None
        previous = os.environ.get("PROOFLOOP_ROLE_ROUTING_JSON")
        try:
            if override:
                os.environ["PROOFLOOP_ROLE_ROUTING_JSON"] = json.dumps(override)
            else:
                os.environ.pop("PROOFLOOP_ROLE_ROUTING_JSON", None)
            result = converge_goal(
                baseline_host if arm == "baseline-routing" else proofloop_host,
                repo,
                task["request"],
                strategy_override=_strategy(task.get("strategy")),
                timeout_seconds=timeout_seconds,
                output_format="quiet",
                stream=io.StringIO(),
            )
        finally:
            if previous is None:
                os.environ.pop("PROOFLOOP_ROLE_ROUTING_JSON", None)
            else:
                os.environ["PROOFLOOP_ROLE_ROUTING_JSON"] = previous

    checks = _run_suite_checks(repo, task.get("checks", []))
    run_dir = Path(result["runDir"])
    try:
        TokScaleAdapter().reconcile(run_dir)
    except Exception:
        pass
    usage = build_usage_summary(run_dir)
    success = result.get("verdict") in {"PASS", "PROVEN"} and all(item["exitCode"] == 0 for item in checks)
    coverage = usage["coverage"]
    return {
        "verdict": "PROVEN" if success else "FAILED",
        "agentVerdict": result.get("verdict"),
        "runDir": str(run_dir),
        "durationSeconds": round(time.monotonic() - started, 6),
        "checks": checks,
        "usage": usage,
        "usageAvailable": coverage["expectedInvocations"] > 0 and coverage["tokenCoverageRatio"] == 1.0,
        "costAvailable": coverage["expectedInvocations"] > 0 and coverage["costedInvocations"] == coverage["expectedInvocations"],
    }


def _run_single_agent(
    repo: Path,
    task: dict[str, Any],
    host: str,
    model: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    started = start_run(repo, task["request"])
    run_dir = Path(started["runDir"])
    checks_text = "\n".join(" ".join(command) for command in task.get("checks", []))
    prompt = (
        "Implement the following objective as a single coding agent. Continue until the objective and acceptance checks pass.\n\n"
        f"Objective:\n{task['request']}\n\nAcceptance checks:\n{checks_text or 'Use the repository tests.'}"
    )
    result = invoke_role(
        host,
        "implementer_fast",
        repo,
        run_dir,
        prompt=prompt,
        timeout_seconds=timeout_seconds,
        task_id=str(task["id"]),
        attempt=1,
        model_override=model,
        invocation_id=f"01-{host}-single-agent",
    )
    invocation = {
        "invocationId": result.get("invocationId"),
        "taskId": task["id"],
        "role": "single_agent",
        "runtime": host,
        "requestedModel": model,
        "observedModel": result.get("observedModel"),
        "sessionId": result.get("sessionId"),
        "usage": result.get("usage"),
    }
    with (run_dir / "invocations.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(invocation, ensure_ascii=False) + "\n")
    build_usage_summary(run_dir)
    return {**result, "runDir": str(run_dir)}


def _run_suite_checks(repo: Path, commands: list[list[str]]) -> list[dict[str, Any]]:
    results = []
    for command in commands:
        completed = subprocess.run(command, cwd=repo, text=True, capture_output=True, check=False)
        results.append(
            {
                "command": command,
                "exitCode": completed.returncode,
                "outputTail": (completed.stdout + completed.stderr).splitlines()[-20:],
            }
        )
    return results


def _single_model_routes(host: str, model: str) -> dict[str, list[dict[str, Any]]]:
    routes = {}
    for role in ROLES:
        routes[role] = [
            {
                "runtime": host,
                "model": model,
                "accessMode": "workspace-write" if role.startswith("implementer") else "read-only",
            }
        ]
    return routes


def _strategy(value: Any) -> str | None:
    return {
        "direct": "DIRECT_VERIFIED_CHANGE",
        "planned": "PLANNED_IMPLEMENTATION",
        "high-risk": "HIGH_RISK_ENGINEERING",
    }.get(value)


def _arm_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    proven = [item for item in items if item.get("verdict") == "PROVEN"]
    usage_complete = bool(items) and all(item.get("usageAvailable") for item in items)
    cost_complete = bool(items) and all(item.get("costAvailable") for item in items)
    token_total = sum(int(item.get("usage", {}).get("totals", {}).get("rawTotal", 0)) for item in items)
    cost_total = sum(float(item.get("usage", {}).get("totals", {}).get("costUsd", 0.0)) for item in items)
    proven_tokens = [int(item["usage"]["totals"]["rawTotal"]) for item in proven if item.get("usageAvailable")]
    return {
        "trials": len(items),
        "proven": len(proven),
        "successRate": round(len(proven) / len(items), 6) if items else 0.0,
        "usageCoverage": round(sum(bool(item.get("usageAvailable")) for item in items) / len(items), 6) if items else 0.0,
        "tokensPerProven": round(token_total / len(proven), 6) if proven and usage_complete else None,
        "medianTokensOnProven": statistics.median(proven_tokens) if proven_tokens else None,
        "costPerProven": round(cost_total / len(proven), 8) if proven and cost_complete else None,
        "medianDurationSeconds": statistics.median(float(item.get("durationSeconds", 0)) for item in items) if items else None,
    }


def _gain(baseline: Any, candidate: Any) -> float | None:
    if not isinstance(baseline, (int, float)) or not isinstance(candidate, (int, float)) or baseline <= 0:
        return None
    return round((baseline - candidate) / baseline * 100, 6)


def _paired_token_gains(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> list[float]:
    candidate_map = {(item["taskId"], item["repetition"]): item for item in candidate}
    gains = []
    for item in baseline:
        other = candidate_map.get((item["taskId"], item["repetition"]))
        if not other or item.get("verdict") != "PROVEN" or other.get("verdict") != "PROVEN":
            continue
        if not item.get("usageAvailable") or not other.get("usageAvailable"):
            continue
        baseline_tokens = int(item["usage"]["totals"]["rawTotal"])
        candidate_tokens = int(other["usage"]["totals"]["rawTotal"])
        if baseline_tokens > 0:
            gains.append((baseline_tokens - candidate_tokens) / baseline_tokens * 100)
    return gains


def _bootstrap_interval(values: list[float], samples: int = 1000) -> list[float]:
    rng = random.Random(0)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(samples))
    return [round(means[int(samples * 0.025)], 6), round(means[int(samples * 0.975) - 1], 6)]


def _copy_trial_artifacts(trial: dict[str, Any], target: Path) -> None:
    source = Path(trial["runDir"])
    target.mkdir(parents=True, exist_ok=True)
    for name in ("run.json", "truth-report.json", "invocations.jsonl", "model-trace.jsonl", "events.jsonl"):
        path = source / name
        if path.exists():
            shutil.copy2(path, target / name)
    if (source / "usage").exists():
        shutil.copytree(source / "usage", target / "usage")
    trial["runDir"] = str(target)


@contextmanager
def _isolated_worktree(repo: Path, baseline: str) -> Iterator[Path]:
    parent = Path(tempfile.mkdtemp(prefix="proofloop-benchmark-"))
    worktree = parent / "repo"
    _git(repo, "worktree", "add", "--detach", str(worktree), baseline)
    try:
        yield worktree
    finally:
        _git(repo, "worktree", "remove", "--force", str(worktree), check=False)
        shutil.rmtree(parent, ignore_errors=True)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed
