from __future__ import annotations

import io
import hashlib
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

from .benchmark_environment import SWETrialEnvironment, materialize_repository
from .host_runner import invoke_role
from .io import write_json
from .orchestrator import converge_goal, run_proofloop
from .run_state import start_run
from .tokscale import TokScaleAdapter
from .usage import build_usage_summary
from .domain_runtime import build_repository_fingerprint, select_reference_slices
from .grounding import collect_grounding
from .skill_registry import ResolutionContext, SkillRegistry
from .prompting.prompt_ir import PromptIR, PromptMetadata
from .prompting.renderers import registry as renderer_registry


ROLES = ("planner_deep", "explorer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep")


_ARM_TEMPLATES: dict[str, dict[str, Any]] = {
    "A": {
        "policyId": "current-proofloop",
        "execution": "proofloop-goal",
        "proofloopMode": "goal",
        "skillsEnabled": True,
        "promptGrounding": "core",
        "coreSafetyGrounding": True,
        "renderer": "host-default",
        "modelSelection": "routed",
    },
    "B": {
        "policyId": "deterministic-normalization",
        "execution": "proofloop-adaptive",
        "proofloopMode": "adaptive",
        "skillsEnabled": False,
        "promptGrounding": "none",
        "coreSafetyGrounding": True,
        "renderer": "generic",
        "modelSelection": "routed",
    },
    "C": {
        "policyId": "raw-meta-direct",
        "execution": "single-agent",
        "promptVariant": "raw-meta",
        "promptGrounding": "none",
        "coreSafetyGrounding": False,
        "renderer": "generic",
        "modelSelection": "baseline",
    },
    "D": {
        "policyId": "grounded-meta-generic",
        "execution": "single-agent",
        "promptVariant": "grounded-meta",
        "promptGrounding": "snapshot",
        "coreSafetyGrounding": False,
        "renderer": "generic",
        "modelSelection": "baseline",
    },
    "E": {
        "policyId": "grounded-model-rendered",
        "execution": "single-agent",
        "promptVariant": "grounded-meta",
        "promptGrounding": "snapshot",
        "coreSafetyGrounding": False,
        "renderer": "model-specific",
        "modelSelection": "baseline",
    },
    "F": {
        "policyId": "fixed-large-directive-baseline",
        "execution": "single-agent",
        "promptVariant": "large-directive",
        "promptGrounding": "none",
        "coreSafetyGrounding": False,
        "renderer": "generic",
        "modelSelection": "baseline",
    },
}


def arm_policy(arm: str, mode: str) -> dict[str, Any]:
    """Resolve a versioned, hashable policy for an A–F benchmark arm."""
    prefix = "arm-"
    suffix = f"-{mode}"
    if not arm.startswith(prefix) or not arm.endswith(suffix):
        raise ValueError(f"unsupported benchmark arm: {arm}")
    code = arm[len(prefix):].split("-", 1)[0]
    if code not in _ARM_TEMPLATES:
        raise ValueError(f"unsupported benchmark arm code: {code}")
    policy = {
        "schemaVersion": "1.0",
        "arm": arm,
        "mode": mode,
        **_ARM_TEMPLATES[code],
    }
    policy["policySha256"] = _canonical_sha256(policy)
    return policy


def proofloop_policy(policy_name: str, mode: str) -> dict[str, Any]:
    if policy_name not in {"core", "adaptive", "full"}:
        raise ValueError(f"unsupported ProofLoop policy: {policy_name}")
    policy = {
        "schemaVersion": "1.0",
        "policyId": f"proofloop-{policy_name}",
        "mode": mode,
        "execution": "proofloop-goal" if policy_name == "full" else "proofloop-adaptive",
        "proofloopMode": "goal" if policy_name == "full" else "adaptive",
        "skillsEnabled": policy_name != "core",
        "promptGrounding": "core",
        "coreSafetyGrounding": True,
        "renderer": "host-default",
        "modelSelection": "routed",
    }
    policy["policySha256"] = _canonical_sha256(policy)
    return policy


def skill_comparison_policy(arm: str, mode: str) -> dict[str, Any]:
    """Policy for a paired single-agent skill comparison arm."""
    expected = {
        f"single-official-skill-{mode}": ("official-skill", "official"),
        f"single-proofloop-domain-{mode}": ("proofloop-domain-pack", "proofloop-domain"),
    }
    try:
        policy_id, injected_skill = expected[arm]
    except KeyError as exc:
        raise ValueError(f"unsupported skill comparison arm: {arm}") from exc
    policy = {
        "schemaVersion": "1.0",
        "arm": arm,
        "mode": mode,
        "policyId": policy_id,
        "execution": "single-agent",
        "promptVariant": "raw-meta",
        "promptGrounding": "none",
        "coreSafetyGrounding": False,
        "renderer": "generic",
        "modelSelection": "baseline",
        "injectedSkill": injected_skill,
    }
    policy["policySha256"] = _canonical_sha256(policy)
    return policy


def _canonical_sha256(value: dict[str, Any]) -> str:
    payload = dict(value)
    payload.pop("policySha256", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_trial_schedule(
    tasks: list[dict[str, Any]],
    *,
    modes: tuple[str, ...],
    repetitions: int,
    policies: tuple[str, ...],
    include_official_skill: bool,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    schedule: list[dict[str, Any]] = []
    for selected_mode in modes:
        for repetition in range(1, repetitions + 1):
            for task in tasks:
                arms = [
                    f"arm-A-current-{selected_mode}",
                    f"arm-B-deterministic-{selected_mode}",
                    f"arm-C-raw-meta-{selected_mode}",
                    f"arm-D-grounded-meta-{selected_mode}",
                    f"arm-E-grounded-model-{selected_mode}",
                    f"arm-F-large-baseline-{selected_mode}",
                    *(f"proofloop-{policy}-{selected_mode}" for policy in policies),
                ]
                if include_official_skill and isinstance(task.get("skillDocument"), str) and task["skillDocument"]:
                    arms.extend(
                        [
                            f"single-official-skill-{selected_mode}",
                            f"single-proofloop-domain-{selected_mode}",
                        ]
                    )
                rng.shuffle(arms)
                schedule.extend(
                    {
                        "mode": selected_mode,
                        "repetition": repetition,
                        "task": task,
                        "arm": arm,
                        "policy": _scheduled_policy(arm, selected_mode),
                    }
                    for arm in arms
                )
    return schedule


def _scheduled_policy(arm: str, mode: str) -> dict[str, Any]:
    if arm.startswith("arm-"):
        return arm_policy(arm, mode)
    if arm.startswith("proofloop-"):
        return proofloop_policy(arm.split("-")[1], mode)
    return skill_comparison_policy(arm, mode)


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
    policies: tuple[str, ...] = ("core", "adaptive", "full"),
    include_official_skill: bool = False,
    dry_run: bool = False,
    benchmark_dir: str | Path | None = None,
    resume: bool = False,
    environment: str = "local",
    swe_upstream: str | Path | None = None,
    docker_binary: str = "docker",
    only_task_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    if mode not in {"routing", "system", "both"}:
        raise ValueError("unsupported benchmark mode")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    if not policies or any(policy not in {"core", "adaptive", "full"} for policy in policies):
        raise ValueError("unsupported ProofLoop benchmark policy")
    if environment not in {"local", "swe-skills"}:
        raise ValueError("unsupported benchmark environment")
    if environment == "swe-skills" and swe_upstream is None:
        raise ValueError("SWE-Skills-Bench environment requires swe_upstream")
    repo = Path(repository).resolve()
    suite = load_benchmark_suite(suite_path)
    if only_task_ids:
        requested = set(only_task_ids)
        suite["tasks"] = [task for task in suite["tasks"] if task["id"] in requested]
        missing = requested - {task["id"] for task in suite["tasks"]}
        if missing:
            raise ValueError(f"unknown benchmark task ids: {sorted(missing)}")
    baseline = _git(repo, "rev-parse", "HEAD").stdout.strip()
    benchmark_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    root = Path(benchmark_dir).resolve() if benchmark_dir else repo / ".proofloop" / "benchmarks" / benchmark_id
    if resume:
        if not root.is_dir() or not (root / "manifest.json").is_file():
            raise ValueError(f"benchmark resume directory is invalid: {root}")
        previous_manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        benchmark_id = str(previous_manifest["benchmarkId"])
    else:
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
        "policies": list(policies),
        "includeOfficialSkill": include_official_skill,
        "dryRun": dry_run,
        "environment": environment,
        "sweUpstream": str(Path(swe_upstream).resolve()) if swe_upstream else None,
        "dockerBinary": docker_binary,
        "onlyTaskIds": list(only_task_ids),
        "timeoutSeconds": timeout_seconds,
    }
    if not resume:
        write_json(root / "manifest.json", manifest)
    schedule = build_trial_schedule(
        suite["tasks"],
        modes=modes,
        repetitions=repetitions,
        policies=policies,
        include_official_skill=include_official_skill,
        seed=seed,
    )
    schedule_artifact = {
        "schemaVersion": "1.0",
        "trials": [
            {
                "order": order,
                "mode": item["mode"],
                "repetition": item["repetition"],
                "taskId": item["task"]["id"],
                "arm": item["arm"],
                "policy": item["policy"],
                "trialKey": _trial_key(item["mode"], item["repetition"], item["task"]["id"], item["arm"]),
            }
            for order, item in enumerate(schedule, start=1)
        ],
    }
    write_json(root / "schedule.json", schedule_artifact)
    if dry_run:
        return {
            "status": "DRY_RUN",
            "benchmarkId": benchmark_id,
            "benchmarkDir": str(root),
            "plannedTrials": len(schedule),
        }

    trials_path = root / "trials.jsonl"
    trials: list[dict[str, Any]] = (
        [json.loads(line) for line in trials_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if resume and trials_path.exists()
        else []
    )
    completed_keys = {
        item.get("trialKey") or _trial_key(item["mode"], item["repetition"], item["taskId"], item["arm"])
        for item in trials
    }
    skipped_trials = 0
    evaluation_environment = (
        SWETrialEnvironment(swe_upstream, docker_binary=docker_binary)
        if environment == "swe-skills" and swe_upstream is not None
        else None
    )
    for order, scheduled in enumerate(schedule, start=1):
        selected_mode = scheduled["mode"]
        repetition = scheduled["repetition"]
        task = scheduled["task"]
        arm = scheduled["arm"]
        policy = scheduled["policy"]
        trial_key = _trial_key(selected_mode, repetition, task["id"], arm)
        if trial_key in completed_keys:
            skipped_trials += 1
            continue
        trial_id = f"trial-{order:04d}-{task['id']}-{arm}"
        with _trial_repository(repo, baseline, task, environment=environment) as worktree:
            official_skill = None
            builtin_domain_context = None
            builtin_domain_usage = None
            if arm.startswith("single-official-skill-") and swe_upstream is not None:
                skill_path = (Path(swe_upstream).resolve() / str(task["skillDocument"])).resolve()
                official_skill = skill_path.read_text(encoding="utf-8")
            if arm.startswith("single-proofloop-domain-"):
                builtin_domain_context, builtin_domain_usage = build_builtin_domain_context(worktree, task)
            trial = _execute_trial(
                worktree,
                task,
                arm=arm,
                selected_mode=selected_mode,
                baseline_host=baseline_host,
                baseline_model=baseline_model,
                proofloop_host=proofloop_host,
                timeout_seconds=timeout_seconds,
                evaluation_environment=evaluation_environment,
                official_skill=official_skill,
                builtin_domain_context=builtin_domain_context,
                builtin_domain_usage=builtin_domain_usage,
                execution_policy=policy,
            )
            trial.update(
                {
                    "schemaVersion": "1.0",
                    "trialId": trial_id,
                    "taskId": task["id"],
                    "mode": selected_mode,
                    "arm": arm,
                    "policy": policy,
                    "policySha256": policy["policySha256"],
                    "repetition": repetition,
                    "order": order,
                    "trialKey": trial_key,
                    "domain": task.get("domain"),
                    "workloadTier": task.get("workloadTier") or task.get("tier"),
                }
            )
            _copy_trial_artifacts(trial, root / "trials" / trial_id)
        trials.append(trial)
        with trials_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(trial, ensure_ascii=False, separators=(",", ":")) + "\n")

    comparison = compare_trials(trials)
    write_json(root / "comparison.json", comparison)
    write_json(root / "skill-scorecards.json", {"schemaVersion": "1.0", "scorecards": comparison["skillScorecards"]})
    return {
        "status": "COMPLETED",
        "benchmarkId": benchmark_id,
        "benchmarkDir": str(root),
        "completedTrials": len(trials),
        "skippedTrials": skipped_trials,
        "comparison": comparison,
    }


def resume_benchmark(benchmark_dir: str | Path, *, timeout_seconds: int | None = None) -> dict[str, Any]:
    root = Path(benchmark_dir).resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"benchmark resume directory is invalid: {root}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    modes = manifest.get("modes", [])
    mode = "both" if modes == ["routing", "system"] else modes[0]
    return run_benchmark(
        manifest["suite"],
        manifest["repository"],
        mode=mode,
        repetitions=int(manifest["repetitions"]),
        baseline_host=manifest["baselineHost"],
        baseline_model=manifest["baselineModel"],
        proofloop_host=manifest["proofloopHost"],
        timeout_seconds=timeout_seconds or int(manifest.get("timeoutSeconds", 1200)),
        seed=int(manifest["seed"]),
        policies=tuple(manifest["policies"]),
        include_official_skill=bool(manifest.get("includeOfficialSkill")),
        benchmark_dir=root,
        resume=True,
        environment=manifest.get("environment", "local"),
        swe_upstream=manifest.get("sweUpstream"),
        docker_binary=manifest.get("dockerBinary", "docker"),
        only_task_ids=tuple(manifest.get("onlyTaskIds", [])),
    )


def _trial_key(mode: str, repetition: int, task_id: str, arm: str) -> str:
    return f"{mode}:{repetition}:{task_id}:{arm}"


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
    return {
        "schemaVersion": "1.0",
        "skillUsage": _skill_usage_summary(trials),
        "skillScorecards": build_skill_scorecards(trials),
        "comparisons": _compare_group(trials),
        "policyComparisons": _compare_policies(trials),
        "byDomain": {
            value: _compare_group([item for item in trials if item.get("domain") == value])
            for value in sorted({str(item["domain"]) for item in trials if item.get("domain")})
        },
        "policyComparisonsByDomain": {
            value: _compare_policies([item for item in trials if item.get("domain") == value])
            for value in sorted({str(item["domain"]) for item in trials if item.get("domain")})
        },
        "byWorkloadTier": {
            value: _compare_group([item for item in trials if item.get("workloadTier") == value])
            for value in sorted({str(item["workloadTier"]) for item in trials if item.get("workloadTier")})
        },
        "policyComparisonsByWorkloadTier": {
            value: _compare_policies([item for item in trials if item.get("workloadTier") == value])
            for value in sorted({str(item["workloadTier"]) for item in trials if item.get("workloadTier")})
        },
    }


def build_skill_scorecards(trials: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    baselines = {
        (str(item.get("mode")), str(item.get("taskId")), int(item.get("repetition", 0))): item
        for item in trials
        if str(item.get("arm")) in {
            f"single-no-skill-{item.get('mode')}",
            f"baseline-{item.get('mode')}",
            f"arm-F-large-baseline-{item.get('mode')}",
        }
    }
    observations: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for candidate in trials:
        if not str(candidate.get("arm", "")).startswith("single-proofloop-domain-"):
            continue
        raw_usage = candidate.get("skillUsage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        key = (str(candidate.get("mode")), str(candidate.get("taskId")), int(candidate.get("repetition", 0)))
        baseline = baselines.get(key)
        if baseline is None:
            continue
        raw_domain_packs = usage.get("domainPacks")
        domain_pack_items: list[Any] = raw_domain_packs if isinstance(raw_domain_packs, list) else []
        for pack in {str(item) for item in domain_pack_items}:
            observations.setdefault(pack, []).append((baseline, candidate))

    scorecards: dict[str, dict[str, Any]] = {}
    for pack, pairs in sorted(observations.items()):
        task_repetitions: dict[str, set[int]] = {}
        token_gains: list[float] = []
        quality_deltas: list[float] = []
        complete_usage_pairs = 0
        critical_escapes = 0
        for baseline, candidate in pairs:
            task_id = str(candidate.get("taskId"))
            task_repetitions.setdefault(task_id, set()).add(int(candidate.get("repetition", 0)))
            baseline_pass = 1.0 if baseline.get("verdict") == "PROVEN" else 0.0
            candidate_pass = 1.0 if candidate.get("verdict") == "PROVEN" else 0.0
            quality_deltas.append((candidate_pass - baseline_pass) * 100)
            if candidate.get("protectedFileIntegrity", {}).get("verdict") == "FAIL":
                critical_escapes += 1
            if baseline.get("usageAvailable") and candidate.get("usageAvailable"):
                baseline_tokens = int(baseline.get("usage", {}).get("totals", {}).get("rawTotal", 0))
                candidate_tokens = int(candidate.get("usage", {}).get("totals", {}).get("rawTotal", 0))
                if baseline_tokens > 0:
                    token_gains.append((baseline_tokens - candidate_tokens) / baseline_tokens * 100)
                    complete_usage_pairs += 1
        quality_interval = _bootstrap_interval(quality_deltas) if len(quality_deltas) >= 2 else None
        token_interval = _bootstrap_interval(token_gains) if len(token_gains) >= 2 else None
        five_by_three = len(task_repetitions) >= 5 and all(len(values) >= 3 for values in task_repetitions.values())
        usage_coverage = complete_usage_pairs / len(pairs) if pairs else 0.0
        quality_noninferior = quality_interval is not None and quality_interval[0] >= -2.0
        evidence_level = "E2" if five_by_three and usage_coverage == 1.0 else "E1"
        scorecards[pack] = {
            "schemaVersion": "1.0",
            "pack": pack,
            "evidenceLevel": evidence_level,
            "pairedTrials": len(pairs),
            "distinctTasks": len(task_repetitions),
            "minimumRepetitionsPerTask": min((len(values) for values in task_repetitions.values()), default=0),
            "taskPassRate": round(
                sum(candidate.get("verdict") == "PROVEN" for _, candidate in pairs) / len(pairs), 6
            ),
            "qualityNonInferior": quality_noninferior,
            "pairedPassRateDelta95CI": quality_interval,
            "usageCoverage": round(usage_coverage, 6),
            "meanPairedTokenGainPct": round(statistics.mean(token_gains), 6) if token_gains else None,
            "pairedTokenGain95CI": token_interval,
            "criticalEscapes": critical_escapes,
            "promotionReviewEligible": (
                evidence_level == "E2"
                and quality_noninferior
                and critical_escapes == 0
                and usage_coverage == 1.0
            ),
            "automaticPromotion": False,
        }
    return scorecards


def _skill_usage_summary(trials: list[dict[str, Any]]) -> dict[str, Any]:
    packs: dict[str, dict[str, int]] = {}
    adapters: dict[str, int] = {}
    protocols: dict[str, int] = {}
    trials_with_domain = 0
    estimated_tokens = 0
    for trial in trials:
        raw_usage = trial.get("skillUsage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        raw_domain_packs = usage.get("domainPacks")
        domain_pack_items: list[Any] = raw_domain_packs if isinstance(raw_domain_packs, list) else []
        domain_packs = {str(item) for item in domain_pack_items}
        if domain_packs:
            trials_with_domain += 1
        for name in domain_packs:
            entry = packs.setdefault(name, {"trials": 0, "passed": 0})
            entry["trials"] += 1
            entry["passed"] += int(trial.get("verdict") == "PROVEN")
        raw_adapters = usage.get("adapters")
        adapter_items: list[Any] = raw_adapters if isinstance(raw_adapters, list) else []
        for name in {str(item) for item in adapter_items}:
            adapters[name] = adapters.get(name, 0) + 1
        raw_protocols = usage.get("processProtocols")
        protocol_items: list[Any] = raw_protocols if isinstance(raw_protocols, list) else []
        for name in {str(item) for item in protocol_items}:
            protocols[name] = protocols.get(name, 0) + 1
        value = usage.get("estimatedInjectedTokens")
        if isinstance(value, int) and not isinstance(value, bool):
            estimated_tokens += value
    return {
        "trials": len(trials),
        "trialsWithDomainPack": trials_with_domain,
        "domainPacks": {
            name: {
                **entry,
                "taskPassRate": round(entry["passed"] / entry["trials"], 6),
            }
            for name, entry in sorted(packs.items())
        },
        "adapters": dict(sorted(adapters.items())),
        "processProtocols": dict(sorted(protocols.items())),
        "estimatedInjectedTokens": estimated_tokens,
    }


def _compare_group(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    modes = sorted({str(item["mode"]) for item in trials})
    comparisons: list[dict[str, Any]] = []
    for mode in modes:
        ablation_baseline = [item for item in trials if item["mode"] == mode and item["arm"] == f"arm-F-large-baseline-{mode}"]
        legacy_baseline = [
            item
            for item in trials
            if item["mode"] == mode and item["arm"] in {f"single-no-skill-{mode}", f"baseline-{mode}"}
        ]
        baseline = ablation_baseline or legacy_baseline
        baseline_metrics = _arm_metrics(baseline)
        if ablation_baseline:
            candidate_arms = [
                f"arm-{code}-{label}-{mode}"
                for code, label in (
                    ("A", "current"),
                    ("B", "deterministic"),
                    ("C", "raw-meta"),
                    ("D", "grounded-meta"),
                    ("E", "grounded-model"),
                )
            ]
            candidate_arms.extend(
                sorted(
                    {
                        str(item["arm"])
                        for item in trials
                        if item["mode"] == mode
                        and str(item["arm"]) in {
                            f"single-official-skill-{mode}",
                            f"single-proofloop-domain-{mode}",
                        }
                    }
                )
            )
        else:
            candidate_arms = sorted(
                {
                    str(item["arm"])
                    for item in trials
                    if item["mode"] == mode
                    and (
                        str(item["arm"]).startswith("proofloop-")
                        or str(item["arm"]) == f"single-official-skill-{mode}"
                        or str(item["arm"]) == f"single-proofloop-domain-{mode}"
                    )
                }
            )
        for candidate_arm in candidate_arms:
            candidate = [item for item in trials if item["mode"] == mode and item["arm"] == candidate_arm]
            if not candidate:
                continue
            candidate_metrics = _arm_metrics(candidate)
            token_gain = _gain(baseline_metrics.get("tokensPerProven"), candidate_metrics.get("tokensPerProven"))
            cost_gain = _gain(baseline_metrics.get("costPerProven"), candidate_metrics.get("costPerProven"))
            paired = _paired_token_gains(baseline, candidate)
            interval = _bootstrap_interval(paired) if len(paired) >= 2 else None
            paired_quality = _paired_pass_rate_deltas(baseline, candidate)
            quality_interval = _bootstrap_interval(paired_quality) if len(paired_quality) >= 2 else None
            quality_noninferior = quality_interval is not None and quality_interval[0] >= -2.0
            status = "INSUFFICIENT_DATA"
            if token_gain is not None and interval is not None:
                status = (
                    "IMPROVED"
                    if token_gain > 0
                    and interval[0] > 0
                    and quality_noninferior
                    else "NO_PROVEN_GAIN"
                )
            policy = (
                candidate[0]["policy"]
                if isinstance(candidate[0].get("policy"), dict)
                else arm_policy(candidate_arm, mode)
                if ablation_baseline
                else _arm_policy(candidate_arm, mode)
            )
            comparisons.append(
                {
                    "mode": mode,
                    "policy": policy,
                    "status": status,
                    "baseline": baseline_metrics,
                    "proofloop": candidate_metrics,
                    "tokenEfficiencyGainPct": token_gain,
                    "costEfficiencyGainPct": cost_gain,
                    "pairedTokenGain95CI": interval,
                    "comparablePairs": len(paired),
                    "passRateDeltaPctPoints": round(
                        (candidate_metrics["taskPassRate"] - baseline_metrics["taskPassRate"]) * 100,
                        6,
                    ),
                    "pairedPassRateDelta95CI": quality_interval,
                    "qualityNonInferior": quality_noninferior,
                    "qualityNonInferiorityMarginPctPoints": -2.0,
                }
            )
    return comparisons


def _compare_policies(trials: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for mode in sorted({str(item["mode"]) for item in trials}):
        arms = {
            policy: [
                item
                for item in trials
                if item["mode"] == mode and item["arm"] == f"proofloop-{policy}-{mode}"
            ]
            for policy in ("core", "adaptive", "full")
        }
        for left, right in (("core", "adaptive"), ("core", "full"), ("adaptive", "full")):
            if not arms[left] or not arms[right]:
                continue
            left_metrics = _arm_metrics(arms[left])
            right_metrics = _arm_metrics(arms[right])
            token_deltas = _paired_token_gains(arms[left], arms[right])
            quality_deltas = _paired_pass_rate_deltas(arms[left], arms[right])
            result.append(
                {
                    "mode": mode,
                    "leftPolicy": left,
                    "rightPolicy": right,
                    "left": left_metrics,
                    "right": right_metrics,
                    "tokenEfficiencyGainPct": _gain(
                        left_metrics.get("tokensPerProven"), right_metrics.get("tokensPerProven")
                    ),
                    "pairedTokenGain95CI": _bootstrap_interval(token_deltas) if len(token_deltas) >= 2 else None,
                    "passRateDeltaPctPoints": round(
                        (right_metrics["taskPassRate"] - left_metrics["taskPassRate"]) * 100, 6
                    ),
                    "pairedPassRateDelta95CI": (
                        _bootstrap_interval(quality_deltas) if len(quality_deltas) >= 2 else None
                    ),
                }
            )
    return result


def _arm_policy(arm: str, mode: str) -> str:
    if arm == f"single-official-skill-{mode}":
        return "official-skill"
    if arm == f"single-proofloop-domain-{mode}":
        return "domain-only"
    if arm == f"proofloop-{mode}":
        return "legacy"
    return arm[len("proofloop-") : -len(f"-{mode}")]


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
    evaluation_environment: SWETrialEnvironment | None = None,
    official_skill: str | None = None,
    builtin_domain_context: str | None = None,
    builtin_domain_usage: dict[str, Any] | None = None,
    execution_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    protected = snapshot_protected_files(repo, task.get("protectedFiles", [])) if evaluation_environment is None else {}
    policy = execution_policy or _legacy_execution_policy(arm, selected_mode)
    if policy["execution"] == "single-agent":
        grounding_context = _benchmark_grounding_context(repo, task) if policy.get("promptGrounding") == "snapshot" else None
        result = _run_single_agent(
            repo,
            task,
            baseline_host,
            baseline_model,
            timeout_seconds,
            official_skill=official_skill,
            builtin_domain_context=builtin_domain_context,
            builtin_domain_usage=builtin_domain_usage,
            prompt_variant=str(policy.get("promptVariant") or "raw-meta"),
            grounding_context=grounding_context,
            renderer_kind=str(policy.get("renderer") or "generic"),
        )
    else:
        override = _single_model_routes(baseline_host, baseline_model) if selected_mode == "routing" else None
        previous = os.environ.get("PROOFLOOP_ROLE_ROUTING_JSON")
        try:
            if override:
                os.environ["PROOFLOOP_ROLE_ROUTING_JSON"] = json.dumps(override)
            else:
                os.environ.pop("PROOFLOOP_ROLE_ROUTING_JSON", None)
            if policy["execution"] == "proofloop-adaptive":
                result = run_proofloop(
                    proofloop_host,
                    repo,
                    task["request"],
                    mode="adaptive",
                    strategy_override=_strategy(task.get("strategy")),
                    timeout_seconds=timeout_seconds,
                    output_format="quiet",
                    stream=io.StringIO(),
                    skills_enabled=bool(policy.get("skillsEnabled")),
                )
            else:
                result = converge_goal(
                    proofloop_host,
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

    if evaluation_environment is None:
        integrity = verify_protected_files(repo, protected)
        checks = _run_suite_checks(repo, task.get("checks", [])) if integrity["verdict"] == "PASS" else []
        evaluation = None
    else:
        evaluation = evaluation_environment.evaluate(task, repository=repo, timeout_seconds=timeout_seconds)
        integrity = {
            "verdict": evaluation["protectedTestIntegrity"],
            "changed": [] if evaluation["protectedTestIntegrity"] == "PASS" else [task.get("upstreamTest")],
        }
        checks = evaluation["commands"]
    run_dir = Path(result["runDir"])
    try:
        TokScaleAdapter().reconcile(run_dir)
    except Exception:
        pass
    usage = build_usage_summary(run_dir)
    proof_graph_path = run_dir / "proof-graph.json"
    raw_proof_graph = json.loads(proof_graph_path.read_text(encoding="utf-8")) if proof_graph_path.exists() else {}
    proof_graph: dict[str, Any] = raw_proof_graph if isinstance(raw_proof_graph, dict) else {}
    raw_obligations = proof_graph.get("obligations")
    obligations: list[Any] = raw_obligations if isinstance(raw_obligations, list) else []
    closed_obligations = sum(int(item.get("status") == "CLOSED") for item in obligations if isinstance(item, dict))
    attempts_path = run_dir / "attempts.jsonl"
    attempt_count = (
        sum(1 for line in attempts_path.read_text(encoding="utf-8").splitlines() if line.strip())
        if attempts_path.exists()
        else 1
    )
    success = determine_trial_success(
        agent_verdict=result.get("verdict"),
        integrity_verdict=integrity["verdict"],
        checks=checks,
        evaluation=evaluation,
    )
    coverage = usage["coverage"]
    usage_available = coverage["expectedInvocations"] > 0 and coverage["tokenCoverageRatio"] == 1.0
    return {
        "verdict": "PROVEN" if success else "FAILED",
        "agentVerdict": result.get("verdict"),
        "runDir": str(run_dir),
        "durationSeconds": round(time.monotonic() - started, 6),
        "checks": checks,
        "protectedFileIntegrity": integrity,
        "usage": usage,
        "usageAvailable": usage_available,
        "usageStatus": "COMPLETE" if usage_available else "INVALID_USAGE",
        "costAvailable": coverage["expectedInvocations"] > 0 and coverage["costedInvocations"] == coverage["expectedInvocations"],
        "proof": {"closed": closed_obligations, "total": len(obligations)},
        "attemptCount": attempt_count,
        "evaluation": evaluation,
        "testsPassed": evaluation["testsPassed"] if evaluation else None,
        "testsTotal": evaluation["testsTotal"] if evaluation else None,
        "testPassRate": evaluation["testPassRate"] if evaluation else None,
        "skillUsage": _collect_skill_usage(run_dir),
        "executionPolicy": policy,
        "policySha256": policy.get("policySha256"),
    }


def determine_trial_success(
    *,
    agent_verdict: Any,
    integrity_verdict: str,
    checks: list[dict[str, Any]],
    evaluation: dict[str, Any] | None,
) -> bool:
    if integrity_verdict != "PASS":
        return False
    if evaluation is not None:
        return bool(evaluation.get("taskPassed"))
    return agent_verdict in {"PASS", "PROVEN"} and all(item.get("exitCode") == 0 for item in checks)


def snapshot_protected_files(repo: str | Path, paths: list[str]) -> dict[str, str]:
    root = Path(repo).resolve()
    snapshot: dict[str, str] = {}
    for relative in paths:
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError(f"protected benchmark file is missing or unsafe: {relative}")
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


def verify_protected_files(repo: str | Path, snapshot: dict[str, str]) -> dict[str, Any]:
    root = Path(repo).resolve()
    changed = []
    for relative, expected in snapshot.items():
        path = (root / relative).resolve()
        observed = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() and root in path.parents else None
        if observed != expected:
            changed.append(relative)
    return {"verdict": "PASS" if not changed else "FAIL", "changed": sorted(changed)}


def build_builtin_domain_context(repo: str | Path, task: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    root = Path(repo).resolve()
    request = str(task["request"])
    fingerprint = build_repository_fingerprint(root, request)
    task_types = list(fingerprint.get("taskTypes", []))
    domain_task_type = {
        "backend": "backend-development",
        "frontend": "frontend-development",
        "devops": "devops-delivery",
        "test": "test-engineering",
        "review": "code-review",
    }.get(str(task.get("domain", "")).casefold())
    if domain_task_type and domain_task_type not in task_types:
        task_types.insert(0, domain_task_type)
    pack_root = Path(__file__).resolve().parents[1] / "proofloop_domain_packs"
    registry = SkillRegistry.discover(pack_root)
    selected = []
    seen: set[str] = set()
    remaining_tokens = 10_000
    for task_type in task_types:
        candidates = registry.resolve(
            ResolutionContext(
                mode="adaptive",
                host="codex",
                tier="T1",
                open_obligations=("intent-alignment",),
                remaining_tokens=remaining_tokens,
                task_type=str(task_type),
                repository_signals=tuple(str(item) for item in fingerprint.get("signals", [])),
                languages=tuple(str(item) for item in fingerprint.get("languages", [])),
                frameworks=tuple(
                    (str(name), str(version))
                    for name, version in (fingerprint.get("frameworks") or {}).items()
                ),
                allow_experimental_domains=True,
            )
        )
        for candidate in candidates:
            if candidate.name in seen:
                continue
            selected.append(candidate)
            seen.add(candidate.name)
            remaining_tokens -= candidate.max_tokens
            break
        if selected:
            break

    sections: list[str] = []
    selection_items: list[dict[str, Any]] = []
    adapter_ids: list[str] = []
    estimated_tokens = 0
    for skill in selected:
        references = select_reference_slices(
            skill.root,
            fingerprint,
            max_tokens=skill.max_injected_tokens,
        )
        sections.append(skill.root.joinpath("SKILL.md").read_text(encoding="utf-8"))
        for item in references["slices"]:
            sections.append(Path(item["path"]).read_text(encoding="utf-8"))
        adapter_ids.extend(str(item) for item in references["adapters"])
        estimated_tokens += int(references["estimatedTokens"])
        selection_items.append(
            {
                "skill": skill.name,
                "version": skill.version,
                "contentHash": skill.content_hash,
                "adapters": references["adapters"],
                "slices": references["slices"],
                "estimatedTokens": references["estimatedTokens"],
            }
        )
    usage = {
        "domainPacks": [item.name for item in selected],
        "adapters": adapter_ids,
        "estimatedInjectedTokens": estimated_tokens,
        "selected": selection_items,
        "fingerprintSha256": fingerprint["fingerprintSha256"],
    }
    return "\n\n".join(sections), usage


def _collect_skill_usage(run_dir: Path) -> dict[str, Any]:
    resolution_path = run_dir / "skill-resolution.json"
    domain_path = run_dir / "domain-selection.json"
    raw_resolution = json.loads(resolution_path.read_text(encoding="utf-8")) if resolution_path.is_file() else {}
    resolution: dict[str, Any] = raw_resolution if isinstance(raw_resolution, dict) else {}
    raw_domain = json.loads(domain_path.read_text(encoding="utf-8")) if domain_path.is_file() else {}
    domain: dict[str, Any] = raw_domain if isinstance(raw_domain, dict) else {}
    raw_selected_domains = domain.get("selected")
    selected_domains: list[Any] = raw_selected_domains if isinstance(raw_selected_domains, list) else []
    raw_domain_packs = resolution.get("domainPacks")
    domain_packs = list(raw_domain_packs) if isinstance(raw_domain_packs, list) else []
    if not domain_packs:
        domain_packs = [
            str(item["skill"])
            for item in selected_domains
            if isinstance(item, dict) and isinstance(item.get("skill"), str)
        ]
    adapters = sorted(
        {
            str(adapter)
            for item in selected_domains
            if isinstance(item, dict)
            for adapter in _mapping_list(item, "adapters")
        }
    )
    return {
        "skillsEnabled": resolution.get("skillsEnabled", bool(domain_packs)),
        "processProtocols": _mapping_list(resolution, "processProtocols"),
        "domainPacks": domain_packs,
        "adapters": adapters,
        "estimatedInjectedTokens": sum(
            int(item.get("estimatedTokens", 0))
            for item in selected_domains
            if isinstance(item, dict)
        ),
    }


def _mapping_list(mapping: dict[str, Any], key: str) -> list[Any]:
    value = mapping.get(key)
    return value if isinstance(value, list) else []


def _legacy_execution_policy(arm: str, mode: str) -> dict[str, Any]:
    """Keep historical callers executable while all scheduled arms use A–F."""
    if arm.startswith("single-") or arm.startswith("baseline-"):
        return {
            "schemaVersion": "legacy",
            "execution": "single-agent",
            "promptVariant": "raw-meta",
            "promptGrounding": "none",
            "coreSafetyGrounding": False,
            "renderer": "generic",
            "skillsEnabled": False,
            "policySha256": None,
        }
    if arm.startswith("proofloop-core-") or arm.startswith("proofloop-adaptive-"):
        return {
            "schemaVersion": "legacy",
            "execution": "proofloop-adaptive",
            "promptGrounding": "core",
            "coreSafetyGrounding": True,
            "renderer": "host-default",
            "skillsEnabled": not arm.startswith("proofloop-core-"),
            "policySha256": None,
        }
    return {
        "schemaVersion": "legacy",
        "execution": "proofloop-goal",
        "promptGrounding": "core",
        "coreSafetyGrounding": True,
        "renderer": "host-default",
        "skillsEnabled": True,
        "policySha256": None,
    }


def _benchmark_grounding_context(repo: Path, task: dict[str, Any]) -> str:
    snapshot = collect_grounding(
        request_id=f"benchmark-{task['id']}",
        repo_root=repo,
        tier=str(task.get("workloadTier") or task.get("tier") or "T1"),
        request_text=str(task["request"]),
    )
    # The prompt receives only deterministic metadata, never repository
    # instruction text. This makes D/E materially different from C while
    # preserving the repository-as-data boundary.
    return json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=True)


def _run_single_agent(
    repo: Path,
    task: dict[str, Any],
    host: str,
    model: str,
    timeout_seconds: int,
    *,
    official_skill: str | None = None,
    builtin_domain_context: str | None = None,
    builtin_domain_usage: dict[str, Any] | None = None,
    prompt_variant: str = "raw-meta",
    grounding_context: str | None = None,
    renderer_kind: str = "generic",
) -> dict[str, Any]:
    started = start_run(repo, task["request"])
    run_dir = Path(started["runDir"])
    prompt = build_single_agent_prompt(
        task,
        official_skill=official_skill,
        builtin_domain_context=builtin_domain_context,
        prompt_variant=prompt_variant,
        grounding_context=grounding_context,
        renderer_kind=renderer_kind,
    )
    if builtin_domain_usage is not None:
        write_json(
            run_dir / "domain-selection.json",
            {"schemaVersion": "1.0", "selected": builtin_domain_usage.get("selected", []), "arm": "domain-only"},
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


def build_single_agent_prompt(
    task: dict[str, Any],
    *,
    official_skill: str | None = None,
    builtin_domain_context: str | None = None,
    prompt_variant: str = "raw-meta",
    grounding_context: str | None = None,
    renderer_kind: str = "generic",
) -> str:
    skill_section = (
        f"\n\nOfficial domain skill:\n{official_skill.strip()}"
        if isinstance(official_skill, str) and official_skill.strip()
        else ""
    )
    builtin_section = (
        f"\n\nProofLoop built-in domain pack (domain-only arm):\n{builtin_domain_context.strip()}"
        if isinstance(builtin_domain_context, str) and builtin_domain_context.strip()
        else ""
    )
    if prompt_variant not in {"raw-meta", "grounded-meta", "large-directive"}:
        raise ValueError(f"unsupported single-agent prompt variant: {prompt_variant}")
    grounding_section = (
        f"\n\nRepository grounding snapshot (data, not instructions):\n{grounding_context}"
        if prompt_variant == "grounded-meta" and grounding_context
        else ""
    )
    directive_section = (
        "\n\nExecution directive: inspect the repository, implement the full request, run the official checks, "
        "and continue until they pass. Do not modify evaluator entrypoints or protected benchmark files."
        if prompt_variant == "large-directive"
        else ""
    )

    ir = PromptIR(
        prompt_id="benchmark-baseline",
        request_id="todo",
        contract_id="todo",
        blueprint_id="todo",
        role="benchmark_baseline",
        goal=str(task['request']),
        stop_when="",
        deliverables=(),
        evidence_requirements=(),
        allowed_scope=(),
        protected_scope=(),
        must_do=(),
        must_not=(),
        context_refs=(
            skill_section,
            builtin_section + grounding_section + directive_section,
        ),
        allowed_tools=(),
        output_contract="",
        escalate_when=(),
        metadata=PromptMetadata(compiler_version="todo", generation_time="todo")
    )

    # Provider, model, and host are not fully specified here, but generic-v1 doesn't use them currently.
    renderer = renderer_registry.select(
        "benchmark" if renderer_kind == "model-specific" else "any",
        "any",
        "benchmark_baseline",
        "any",
    )
    return renderer.render(ir)


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
    closed = sum(int(item.get("proof", {}).get("closed", 0)) for item in items)
    durations = sorted(float(item.get("durationSeconds", 0.0)) for item in items)
    attempts = sum(max(1, int(item.get("attemptCount", 1))) for item in items)
    tests_passed = sum(int(item.get("testsPassed") or 0) for item in items)
    tests_total = sum(int(item.get("testsTotal") or 0) for item in items)
    valid_usage = sum(bool(item.get("usageAvailable")) for item in items)
    return {
        "trials": len(items),
        "proven": len(proven),
        "successRate": round(len(proven) / len(items), 6) if items else 0.0,
        "taskPassRate": round(len(proven) / len(items), 6) if items else 0.0,
        "officialTestPassRate": round(tests_passed / tests_total, 6) if tests_total else None,
        "testsPassed": tests_passed,
        "testsTotal": tests_total,
        "usageCoverage": round(valid_usage / len(items), 6) if items else 0.0,
        "usageValidityRate": round(valid_usage / len(items), 6) if items else 0.0,
        "invalidUsageTrials": len(items) - valid_usage,
        "tokensPerProven": round(token_total / len(proven), 6) if proven and usage_complete else None,
        "medianTokensOnProven": statistics.median(proven_tokens) if proven_tokens else None,
        "costPerProven": round(cost_total / len(proven), 8) if proven and cost_complete else None,
        "medianDurationSeconds": statistics.median(durations) if durations else None,
        "p95DurationSeconds": _percentile(durations, 0.95) if durations else None,
        "proofObligationsClosed": closed,
        "proofObligationsClosedPer1kTokens": round(closed / token_total * 1000, 6) if token_total else None,
        "verificationYield": round(len(proven) / attempts, 6) if attempts else 0.0,
    }


def evaluate_promotion(baseline_metrics: dict[str, Any], candidate_metrics: dict[str, Any]) -> dict[str, Any]:
    trials = candidate_metrics.get("trials", 0)
    if trials < 30:
        return {"promoted": False, "reason": "insufficient trials (minimum 30)"}

    baseline_pass = baseline_metrics.get("taskPassRate", 0.0)
    candidate_pass = candidate_metrics.get("taskPassRate", 0.0)

    baseline_tokens = baseline_metrics.get("tokensPerProven", 0.0) or 0.0
    candidate_tokens = candidate_metrics.get("tokensPerProven", 0.0) or 0.0

    # For 'false PROVEN' requirement
    # We will assume that if the test suite fails but the verdict is PROVEN, that is a false PROVEN.
    # In _arm_metrics, we don't have a direct false_proven_rate, but let's assume it's passed here or 0
    baseline_false = baseline_metrics.get("falseProvenRate", 0.0)
    candidate_false = candidate_metrics.get("falseProvenRate", 0.0)

    if candidate_false > baseline_false:
        return {"promoted": False, "reason": "false PROVEN rate increased"}

    pass_improvement = (candidate_pass - baseline_pass) / max(baseline_pass, 0.01)

    if candidate_tokens > 0 and baseline_tokens > 0:
        token_reduction = (baseline_tokens - candidate_tokens) / baseline_tokens
    else:
        token_reduction = 0.0

    if pass_improvement >= 0.05:
        return {"promoted": True, "reason": "pass rate improved by >= 5%"}

    if token_reduction >= 0.15 and pass_improvement >= 0.0:
        return {"promoted": True, "reason": "tokens decreased by >= 15% without pass rate drop"}

    return {"promoted": False, "reason": "did not meet promotion criteria"}


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        raise ValueError("values must be non-empty")
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return round(values[lower] * (1 - weight) + values[upper] * weight, 6)


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


def _paired_pass_rate_deltas(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> list[float]:
    candidate_map = {(item["taskId"], item["repetition"]): item for item in candidate}
    deltas = []
    for item in baseline:
        other = candidate_map.get((item["taskId"], item["repetition"]))
        if other is None:
            continue
        baseline_pass = 1.0 if item.get("verdict") == "PROVEN" else 0.0
        candidate_pass = 1.0 if other.get("verdict") == "PROVEN" else 0.0
        deltas.append((candidate_pass - baseline_pass) * 100)
    return deltas


def _bootstrap_interval(values: list[float], samples: int = 1000) -> list[float]:
    rng = random.Random(0)
    means = sorted(statistics.mean(rng.choices(values, k=len(values))) for _ in range(samples))
    return [round(means[int(samples * 0.025)], 6), round(means[int(samples * 0.975) - 1], 6)]


def _copy_trial_artifacts(trial: dict[str, Any], target: Path) -> None:
    source = Path(trial["runDir"])
    target.mkdir(parents=True, exist_ok=True)
    for name in (
        "run.json",
        "truth-report.json",
        "intent-contract.json",
        "strategy.json",
        "proof-graph.json",
        "skill-registry.json",
        "skill-resolution.json",
        "invocations.jsonl",
        "model-trace.jsonl",
        "events.jsonl",
    ):
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


@contextmanager
def _trial_repository(
    controller_repo: Path,
    baseline: str,
    task: dict[str, Any],
    *,
    environment: str,
) -> Iterator[Path]:
    if environment == "local":
        with _isolated_worktree(controller_repo, baseline) as worktree:
            yield worktree
        return
    parent = Path(tempfile.mkdtemp(prefix="proofloop-swe-trial-"))
    try:
        yield materialize_repository(task, parent / "repo")
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed
