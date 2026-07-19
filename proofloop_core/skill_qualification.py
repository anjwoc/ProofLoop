from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from .domain_runtime import classify_task_types
from .skill_registry import SkillRegistry


TRIGGER_F1_THRESHOLD = 0.85
IRRELEVANT_ACTIVATION_THRESHOLD = 0.05
BEHAVIOR_ARMS = ("single-no-skill", "single-proofloop-domain")


def qualify_domain_packs(
    root: str | Path,
    *,
    only: tuple[str, ...] = (),
    external_catalog: str | Path | None = None,
) -> dict[str, Any]:
    pack_root = Path(root).resolve()
    registry = SkillRegistry.discover(pack_root)
    requested = set(only)
    unknown = requested - {skill.name for skill in registry.skills}
    if unknown:
        raise ValueError(f"unknown domain packs: {sorted(unknown)}")
    catalog = _load_external_catalog(external_catalog) if external_catalog is not None else None
    packs: list[dict[str, Any]] = []
    for skill in registry.skills:
        if requested and skill.name not in requested:
            continue
        trigger_path = skill.root / "evals" / "triggers.json"
        behavior_path = skill.root / "evals" / "behavior.json"
        trigger = evaluate_trigger_fixture(skill.name, trigger_path)
        behavior = validate_behavior_fixture(behavior_path)
        public_scenarios = [
            {
                "id": scenario["id"],
                "request": scenario["request"],
                "scenarioHash": _json_hash({"id": scenario["id"], "request": scenario["request"]}),
            }
            for scenario in behavior
        ]
        pack_report = {
            "pack": skill.name,
            "version": skill.version,
            "status": skill.status,
            "bundleSha256": skill.content_hash,
            "triggerEvaluation": trigger,
            "behaviorEvaluation": {
                "status": "PENDING_AGENT_BEHAVIOR_EVAL",
                "fixtureSha256": hashlib.sha256(behavior_path.read_bytes()).hexdigest(),
                "scenarioCount": len(public_scenarios),
                "scenarios": public_scenarios,
            },
        }
        if catalog is not None:
            pack_report["externalTriggerEvaluation"] = evaluate_external_catalog(skill.name, catalog)
        packs.append(pack_report)
    trigger_ready = all(
        item["triggerEvaluation"]["f1"] >= TRIGGER_F1_THRESHOLD
        and item["triggerEvaluation"]["irrelevantActivationRate"] <= IRRELEVANT_ACTIVATION_THRESHOLD
        for item in packs
    )
    stable = {
        "schemaVersion": "1.0",
        "thresholds": {
            "triggerF1": TRIGGER_F1_THRESHOLD,
            "irrelevantActivationRate": IRRELEVANT_ACTIVATION_THRESHOLD,
        },
        "packs": packs,
    }
    if catalog is not None:
        stable["externalCatalog"] = {
            "path": str(catalog["path"]),
            "sha256": catalog["sha256"],
            "repository": catalog["repository"],
            "commit": catalog["commit"],
            "taskCount": len(catalog["tasks"]),
        }
    return {
        **stable,
        "status": "READY_FOR_BEHAVIOR_EVAL" if trigger_ready else "TRIGGER_QUALIFICATION_FAILED",
        "qualificationHash": _json_hash(stable),
    }


def build_behavior_trial_schedule(
    qualification: dict[str, Any],
    *,
    repetitions: int,
    seed: int = 0,
) -> dict[str, Any]:
    """Build a paired agent-evaluation plan without exposing hidden behavior rubrics."""
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions < 1:
        raise ValueError("behavior repetitions must be a positive integer")
    qualification_hash = qualification.get("qualificationHash")
    packs = qualification.get("packs")
    if not isinstance(qualification_hash, str) or not isinstance(packs, list):
        raise ValueError("invalid qualification report")
    trials: list[dict[str, Any]] = []
    for pack in packs:
        behavior = pack.get("behaviorEvaluation") if isinstance(pack, dict) else None
        scenarios = behavior.get("scenarios") if isinstance(behavior, dict) else None
        if not isinstance(scenarios, list):
            raise ValueError("qualification report is missing behavior scenarios")
        for scenario in scenarios:
            for repetition in range(1, repetitions + 1):
                for arm in BEHAVIOR_ARMS:
                    identity = {
                        "qualificationHash": qualification_hash,
                        "pack": pack["pack"],
                        "scenarioHash": scenario["scenarioHash"],
                        "repetition": repetition,
                        "arm": arm,
                    }
                    trials.append(
                        {
                            "trialId": _json_hash(identity)[:20],
                            "pack": pack["pack"],
                            "packVersion": pack["version"],
                            "scenarioId": scenario["id"],
                            "scenarioHash": scenario["scenarioHash"],
                            "request": scenario["request"],
                            "repetition": repetition,
                            "arm": arm,
                        }
                    )
    random.Random(seed).shuffle(trials)
    stable = {
        "schemaVersion": "1.0",
        "status": "PLANNED",
        "qualificationHash": qualification_hash,
        "arms": list(BEHAVIOR_ARMS),
        "repetitions": repetitions,
        "seed": seed,
        "plannedTrials": len(trials),
        "trials": trials,
    }
    return {**stable, "scheduleHash": _json_hash(stable)}


def evaluate_trigger_fixture(pack_name: str, path: str | Path) -> dict[str, Any]:
    fixture_path = Path(path)
    try:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{fixture_path}: invalid trigger JSON") from exc
    if not isinstance(raw, dict) or raw.get("schemaVersion") != "1.0":
        raise ValueError(f"{fixture_path}: trigger fixture requires schemaVersion 1.0")
    positive = _unique_strings(raw.get("positive"), fixture_path, "positive")
    negative = _unique_strings(raw.get("negative"), fixture_path, "negative")
    if len(positive) < 5 or len(negative) < 5:
        raise ValueError(f"{fixture_path}: at least five positive and negative prompts are required")
    result = _evaluate_prompts(pack_name, positive, negative)
    return {
        "fixtureSha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        **result,
    }


def evaluate_external_catalog(pack_name: str, catalog: dict[str, Any]) -> dict[str, Any]:
    expected_domain = {
        "backend-development": "backend",
        "frontend-development": "frontend",
        "devops-delivery": "devops",
        "test-engineering": "test",
        "code-review": "review",
    }[pack_name]
    positive = [str(item["name"]) for item in catalog["tasks"] if item["domain"] == expected_domain]
    negative = [str(item["name"]) for item in catalog["tasks"] if item["domain"] != expected_domain]
    if not positive:
        return {
            "status": "NOT_COVERED",
            "positiveCount": 0,
            "negativeCount": len(negative),
            "sourceSha256": catalog["sha256"],
        }
    return {"status": "MEASURED", "sourceSha256": catalog["sha256"], **_evaluate_prompts(pack_name, positive, negative)}


def _evaluate_prompts(pack_name: str, positive: list[str], negative: list[str]) -> dict[str, Any]:
    false_negatives = [prompt for prompt in positive if pack_name not in classify_task_types(prompt)]
    false_positives = [prompt for prompt in negative if pack_name in classify_task_types(prompt)]
    true_positive = len(positive) - len(false_negatives)
    precision = true_positive / (true_positive + len(false_positives)) if true_positive + len(false_positives) else 0.0
    recall = true_positive / len(positive)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "positiveCount": len(positive),
        "negativeCount": len(negative),
        "truePositiveCount": true_positive,
        "falseNegativeCount": len(false_negatives),
        "falsePositiveCount": len(false_positives),
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
        "irrelevantActivationRate": round(len(false_positives) / len(negative), 6),
        "falseNegativePrompts": false_negatives,
        "falsePositivePrompts": false_positives,
    }


def _load_external_catalog(path: str | Path) -> dict[str, Any]:
    catalog_path = Path(path).resolve()
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{catalog_path}: invalid external catalog JSON") from exc
    tasks = raw.get("tasks") if isinstance(raw, dict) else None
    if raw.get("schemaVersion") != "1.0" or not isinstance(tasks, list) or not tasks:
        raise ValueError(f"{catalog_path}: invalid external catalog")
    normalized: list[dict[str, str]] = []
    for item in tasks:
        if not isinstance(item, dict):
            raise ValueError(f"{catalog_path}: catalog tasks must be objects")
        normalized.append(
            {
                "id": _required_string(item.get("id"), catalog_path, "task.id"),
                "name": _required_string(item.get("name"), catalog_path, "task.name"),
                "domain": _required_string(item.get("domain"), catalog_path, "task.domain"),
            }
        )
    return {
        "path": catalog_path,
        "sha256": hashlib.sha256(catalog_path.read_bytes()).hexdigest(),
        "repository": _required_string(raw.get("upstreamRepository"), catalog_path, "upstreamRepository"),
        "commit": _required_string(raw.get("upstreamCommit"), catalog_path, "upstreamCommit"),
        "tasks": normalized,
    }


def validate_behavior_fixture(path: str | Path) -> list[dict[str, Any]]:
    fixture_path = Path(path)
    try:
        raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{fixture_path}: invalid behavior JSON") from exc
    if not isinstance(raw, dict) or raw.get("schemaVersion") != "1.0":
        raise ValueError(f"{fixture_path}: behavior fixture requires schemaVersion 1.0")
    scenarios = raw.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) < 3:
        raise ValueError(f"{fixture_path}: at least three behavior scenarios are required")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise ValueError(f"{fixture_path}: behavior scenarios must be objects")
        scenario_id = _required_string(scenario.get("id"), fixture_path, "id")
        if scenario_id in seen:
            raise ValueError(f"{fixture_path}: duplicate behavior scenario id {scenario_id}")
        seen.add(scenario_id)
        request = _required_string(scenario.get("request"), fixture_path, "request")
        requires = _unique_strings(scenario.get("requires"), fixture_path, f"{scenario_id}.requires")
        forbids = _unique_strings(scenario.get("forbids"), fixture_path, f"{scenario_id}.forbids")
        if set(item.casefold() for item in requires).intersection(item.casefold() for item in forbids):
            raise ValueError(f"{fixture_path}: scenario {scenario_id} has contradictory assertions")
        validated.append({"id": scenario_id, "request": request, "requires": requires, "forbids": forbids})
    return validated


def _unique_strings(value: Any, path: Path, field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{path}: {field} must be an array of non-empty strings")
    result = [item.strip() for item in value]
    if len({item.casefold() for item in result}) != len(result):
        raise ValueError(f"{path}: {field} contains duplicates")
    return result


def _required_string(value: Any, path: Path, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: {field} must be a non-empty string")
    return value.strip()


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
