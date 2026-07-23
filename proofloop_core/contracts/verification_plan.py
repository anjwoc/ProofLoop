from __future__ import annotations

import hashlib
import json
import shlex
import copy
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from proofloop_core.context.grounding import CommandCatalog
from proofloop_core.context.io import sha256_file
from proofloop_core.contracts.task_brief import CheckSpec, TaskBrief


SCHEMA_VERSION = "1.0"
def normalize_command(command: Iterable[str]) -> tuple[str, ...]:
    parts = [str(part) for part in command]
    if not parts:
        raise ValueError("verification command must not be empty")
    executable = Path(parts[0]).name.casefold()
    if executable.startswith("python"):
        parts[0] = "<python>"
    return tuple(parts)


def _digest(command: Iterable[str]) -> str:
    payload = json.dumps(normalize_command(command), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _plan_hash(plan: dict[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("planSha256", None)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compile_verification_plan(
    *,
    criterion_ids: Iterable[str],
    tasks: Iterable[TaskBrief],
    command_catalog: CommandCatalog,
    repository: Path | None = None,
    baseline_commit: str | None = None,
    baseline_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    criteria = tuple(dict.fromkeys(str(item) for item in criterion_ids if str(item)))
    if baseline_plan is not None:
        mandatory = copy.deepcopy(list(baseline_plan.get("mandatoryChecks", [])))
        evaluator_inputs = copy.deepcopy(list(baseline_plan.get("evaluatorInputs", [])))
        repository_baseline = baseline_plan.get("repositoryBaseline")
    else:
        mandatory = []
        for index, command_text in enumerate(command_catalog.tests, start=1):
            command = shlex.split(command_text)
            mandatory.append(
                {
                    "checkId": f"CORE-TEST-{index:03d}",
                    "name": "core-repository-tests",
                    "command": command,
                    "commandSha256": _digest(command),
                    "source": "REPOSITORY_DISCOVERED",
                    "authority": "DETERMINISTIC_CHECK",
                    "criterionIds": list(criteria),
                    "mandatory": True,
                }
            )
        evaluator_inputs = _evaluator_inputs(repository, mandatory)
        repository_baseline = baseline_commit

    mandatory_by_digest = {item["commandSha256"]: item for item in mandatory}
    for item in mandatory:
        item["criterionIds"] = []
    candidates: list[dict[str, Any]] = []
    candidate_index = 0
    mandatory_digests = {item["commandSha256"] for item in mandatory}
    for task in tasks:
        linked = task.criterion_ids
        for check in task.required_checks:
            candidate_index += 1
            digest = _digest(check.command)
            if digest in mandatory_by_digest:
                mandatory_by_digest[digest]["criterionIds"] = list(
                    dict.fromkeys([*mandatory_by_digest[digest]["criterionIds"], *linked])
                )
            candidates.append(
                {
                    "checkId": f"CANDIDATE-{candidate_index:03d}",
                    "taskId": task.task_id,
                    "name": check.name,
                    "command": list(check.command),
                    "commandSha256": digest,
                    "source": "REPOSITORY_DISCOVERED" if digest in mandatory_digests else "MODEL_PROPOSED",
                    "authority": "DETERMINISTIC_CHECK" if digest in mandatory_digests else "MODEL_CLAIM",
                    "criterionIds": list(linked),
                    "mandatory": False,
                }
            )

    plan = {
        "schemaVersion": SCHEMA_VERSION,
        "criterionIds": list(criteria),
        "mandatoryChecks": mandatory,
        "candidateChecks": candidates,
        "repositoryBaseline": repository_baseline,
        "evaluatorInputs": evaluator_inputs,
        "status": "READY" if mandatory else "INSUFFICIENT_AUTHORITY",
    }
    plan["planSha256"] = _plan_hash(plan)
    return plan


def _evaluator_inputs(repository: Path | None, checks: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """Fingerprint executable entrypoints/configuration, not editable test cases.

    Test source may be a legitimate deliverable of a behavior change.  In
    contrast, changing the command entrypoint or test framework configuration
    during a run can make a passing result self-referential.  Those inputs are
    frozen from the Core pre-mutation snapshot and checked again at truth time.
    """
    if repository is None:
        return []
    root = Path(repository).resolve()
    paths: set[Path] = set()
    for check in checks:
        command = check.get("command")
        if not isinstance(command, list):
            continue
        for raw in command[1:]:
            candidate = (root / str(raw)).resolve()
            if candidate.is_file() and (candidate == root or root in candidate.parents):
                paths.add(candidate)
        executable = Path(str(command[0])).name.casefold() if command else ""
        if executable in {"npm", "pnpm", "yarn", "bun"}:
            paths.add(root / "package.json")
        if executable == "make":
            paths.add(root / "Makefile")
        if executable.startswith("python") or "pytest" in command:
            for config_name in ("pyproject.toml", "pytest.ini", "tox.ini", "setup.cfg"):
                paths.add(root / config_name)
    return [
        {"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
        for path in sorted(paths)
        if path.is_file()
    ]



def with_mandatory_checks(task: TaskBrief, plan: dict[str, Any]) -> TaskBrief:
    existing = {_digest(check.command) for check in task.required_checks}
    additions = []
    for item in plan.get("mandatoryChecks", []):
        command = item.get("command")
        if not isinstance(command, list) or not command or _digest(command) in existing:
            continue
        additions.append(
            CheckSpec(
                command=[str(part) for part in command],
                name=str(item.get("name") or item.get("checkId")),
            )
        )
        existing.add(_digest(command))
    return replace(task, required_checks=(*task.required_checks, *additions))


def authoritative_passed_criteria(plan: dict[str, Any], checks: dict[str, Any]) -> set[str]:
    mandatory = plan.get("mandatoryChecks")
    results = checks.get("checks")
    if not isinstance(mandatory, list) or not mandatory or not isinstance(results, list):
        return set()
    passed_digests = {
        _digest(item["command"])
        for item in results
        if isinstance(item, dict)
        and isinstance(item.get("command"), list)
        and item.get("status") == "PASS"
    }
    required_digests = {
        str(item.get("commandSha256"))
        for item in mandatory
        if isinstance(item, dict) and item.get("mandatory") is True
    }
    if not required_digests or not required_digests.issubset(passed_digests):
        return set()
    return {
        str(criterion_id)
        for item in mandatory
        if isinstance(item, dict)
        for criterion_id in item.get("criterionIds", [])
        if isinstance(criterion_id, str) and criterion_id
    }
