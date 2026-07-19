from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


REQUIRED_DOMAINS = ("backend", "frontend", "devops")


def build_swe_suite(
    upstream_root: str | Path,
    catalog_path: str | Path,
    *,
    domains: tuple[str, ...] = REQUIRED_DOMAINS,
) -> dict[str, Any]:
    root = Path(upstream_root).resolve()
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    if catalog.get("schemaVersion") != "1.0" or not isinstance(catalog.get("tasks"), list):
        raise ValueError("invalid SWE-Skills-Bench catalog")
    selected_domains = set(domains)
    unknown = selected_domains - set(REQUIRED_DOMAINS)
    if unknown:
        raise ValueError(f"unsupported SWE-Skills-Bench domains: {sorted(unknown)}")
    tasks: list[dict[str, Any]] = []
    config_path = root / "config" / "benchmark_config.yaml"
    if not config_path.is_file():
        raise ValueError("upstream benchmark config is missing")
    for item in catalog["tasks"]:
        if item.get("domain") not in selected_domains:
            continue
        task_id = str(item["id"])
        prompt_path = root / "tasks" / "batch1" / f"{task_id}.md"
        skill_path = root / "skills" / task_id / "SKILL.md"
        test_path = root / "tests" / "batch1" / f"test_{task_id.replace('-', '_')}.py"
        if not prompt_path.exists() or not skill_path.exists() or not test_path.exists():
            raise ValueError(f"upstream task, skill, or test missing for {task_id}")
        checks = item.get("checks")
        if not isinstance(checks, list) or any(
            not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command)
            for command in checks
        ):
            raise ValueError(f"catalog checks must be argv arrays for {task_id}")
        workspace_directory = item.get("workspaceDirectory") or str(item["repoUrl"]).rstrip("/").rsplit("/", 1)[-1]
        if workspace_directory.endswith(".git"):
            workspace_directory = workspace_directory[:-4]
        if not workspace_directory or workspace_directory in {".", ".."} or any(
            separator in workspace_directory for separator in ("/", "\\")
        ):
            raise ValueError(f"invalid workspace directory for {task_id}")
        tasks.append(
            {
                "id": task_id,
                "name": item["name"],
                "request": prompt_path.read_text(encoding="utf-8").strip(),
                "domain": item["domain"],
                "type": item["type"],
                "workloadTier": item.get("workloadTier", "T2"),
                "checks": checks,
                "repository": {"url": item["repoUrl"], "commit": item["repoCommit"]},
                "workspaceDirectory": workspace_directory,
                "dockerImage": (
                    f"{item['dockerImage']}@{item['dockerImageDigest']}"
                    if item.get("dockerImageDigest")
                    else item["dockerImage"]
                ),
                "upstreamTest": f"tests/batch1/test_{task_id.replace('-', '_')}.py",
                "skillDocument": f"skills/{task_id}/SKILL.md",
                "skillDocumentHash": hashlib.sha256(skill_path.read_bytes()).hexdigest(),
                "testDocumentHash": hashlib.sha256(test_path.read_bytes()).hexdigest(),
            }
        )
    return {
        "schemaVersion": "1.0",
        "name": "ProofLoop SWE-Skills-Bench domain suite",
        "source": {
            "name": "SWE-Skills-Bench",
            "repository": "https://github.com/GeniusHTX/SWE-Skills-Bench",
            "commit": catalog["upstreamCommit"],
            "configHash": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        },
        "comparisonPolicies": ["single-model", "adaptive", "full"],
        "tasks": tasks,
    }


def inspect_swe_suite(suite: dict[str, Any]) -> dict[str, Any]:
    tasks = suite.get("tasks") if isinstance(suite, dict) else None
    if not isinstance(tasks, list):
        raise ValueError("suite tasks must be an array")
    counts = Counter(str(item.get("domain")) for item in tasks if isinstance(item, dict))
    domains = {domain: counts.get(domain, 0) for domain in REQUIRED_DOMAINS}
    missing = [domain for domain, count in domains.items() if count == 0]
    invalid = [
        item.get("id")
        for item in tasks
        if not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or not isinstance(item.get("request"), str)
        or not isinstance(item.get("checks"), list)
    ]
    source = suite.get("source") if isinstance(suite.get("source"), dict) else {}
    commit = source.get("commit")
    if not isinstance(commit, str) or len(commit) != 40:
        invalid.append("SOURCE_COMMIT")
    status = "READY" if not missing and not invalid else "BLOCKED"
    return {
        "schemaVersion": "1.0",
        "status": status,
        "taskCount": len(tasks),
        "domains": domains,
        "missingDomains": missing,
        "invalid": invalid,
        "source": source,
        "dockerRequired": True,
    }
