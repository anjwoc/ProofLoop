from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Any

from .task_brief import TaskBrief

_SKIP_PATTERN = re.compile(r"^\+.*(?:\.skip\s*\(|\.only\s*\(|@Disabled\b|@Ignore\b|pytest\.mark\.skip|unittest\.skip)", re.I)
_ASSERT_REMOVAL_PATTERN = re.compile(r"^-.*\b(?:assert|expect\s*\(|assertThat\s*\(|should\b)", re.I)
_TIMEOUT_INCREASE_PATTERN = re.compile(r"^\+.*(?:timeout|setTimeout).*\b(?:[5-9]\d{3,}|\d{5,})\b", re.I)
_DEPENDENCY_FILES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "pyproject.toml",
    "poetry.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "Pipfile",
    "Pipfile.lock",
    "uv.lock",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "Gemfile",
    "Gemfile.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "gradle/libs.versions.toml",
}


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or f"git {' '.join(args)} failed")
    return completed.stdout


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("*/")) for pattern in patterns)


def _is_dependency_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized in _DEPENDENCY_FILES or Path(normalized).name in _DEPENDENCY_FILES


def _is_ephemeral_generated(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    return (
        "__pycache__" in parts
        or ".pytest_cache" in parts
        or ".mypy_cache" in parts
        or ".ruff_cache" in parts
        or normalized.endswith(".pyc")
        or normalized.endswith(".pyo")
        or Path(normalized).name in {".coverage", ".DS_Store"}
    )


def _untracked_files(repo: Path) -> list[str]:
    output = _git(repo, "ls-files", "--others", "--exclude-standard")
    return [
        line.strip()
        for line in output.splitlines()
        if line.strip()
        and not line.strip().startswith(".proofloop")
        and not _is_ephemeral_generated(line.strip())
    ]


def _numstat_metrics(repo: Path, baseline: str, untracked: list[str]) -> dict[str, int]:
    output = _git(repo, "diff", "--numstat", baseline, "--")
    added = 0
    deleted = 0
    files = 0
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        add_raw, del_raw, _ = parts
        files += 1
        if add_raw.isdigit():
            added += int(add_raw)
        if del_raw.isdigit():
            deleted += int(del_raw)
    for relative in untracked:
        path = repo / relative
        if path.is_file():
            try:
                added += len(path.read_text(encoding="utf-8").splitlines())
            except UnicodeDecodeError:
                pass
            files += 1
    return {"changedFiles": files, "addedLines": added, "deletedLines": deleted}


def inspect_diff(task: TaskBrief, repository: str | Path, baseline: str = "HEAD") -> dict[str, Any]:
    repo = Path(repository).resolve()
    name_status = _git(repo, "diff", "--name-status", baseline, "--")
    patch = _git(repo, "diff", "--unified=0", baseline, "--")
    untracked = _untracked_files(repo)
    metrics = _numstat_metrics(repo, baseline, untracked)
    changed: list[dict[str, str]] = []
    violations: list[dict[str, str]] = []
    new_files = 0
    dependency_changes: list[str] = []

    entries: list[tuple[str, str]] = []
    for line in name_status.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        entries.append((parts[0], parts[-1]))
    entries.extend(("A", path) for path in untracked)

    for status, path in entries:
        changed.append({"status": status, "path": path})
        if status.startswith("A"):
            new_files += 1
        if _is_dependency_file(path):
            dependency_changes.append(path)
        if task.allowed_paths and not _matches_any(path, task.allowed_paths):
            violations.append({"code": "SCOPE_VIOLATION", "path": path, "detail": "outside allowedPaths"})
        if task.protected_paths and _matches_any(path, task.protected_paths):
            violations.append({"code": "PROTECTED_PATH_CHANGED", "path": path, "detail": "protectedPaths match"})
        lowered = path.lower()
        if status.startswith("D") and any(token in lowered for token in ("test", "spec")):
            violations.append({"code": "TEST_DELETED", "path": path, "detail": "test file deleted"})

    for relative in untracked:
        path = repo / relative
        if not path.is_file():
            continue
        try:
            patch += "\n+++ b/" + relative + "\n" + "\n".join("+" + line for line in path.read_text(encoding="utf-8").splitlines())
        except UnicodeDecodeError:
            pass

    current_file = ""
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
        elif _SKIP_PATTERN.search(line):
            violations.append({"code": "TEST_DISABLED", "path": current_file, "detail": line[1:].strip()})
        elif _ASSERT_REMOVAL_PATTERN.search(line):
            violations.append({"code": "ASSERTION_REMOVED", "path": current_file, "detail": line[1:].strip()})
        elif _TIMEOUT_INCREASE_PATTERN.search(line):
            violations.append({"code": "TIMEOUT_INCREASED", "path": current_file, "detail": line[1:].strip()})

    metrics["newFiles"] = new_files
    if metrics["changedFiles"] > task.change_budget.max_changed_files:
        violations.append({
            "code": "CHANGED_FILE_BUDGET_EXCEEDED",
            "path": "",
            "detail": f"{metrics['changedFiles']} > {task.change_budget.max_changed_files}",
        })
    if metrics["addedLines"] > task.change_budget.max_added_lines:
        violations.append({
            "code": "ADDED_LINE_BUDGET_EXCEEDED",
            "path": "",
            "detail": f"{metrics['addedLines']} > {task.change_budget.max_added_lines}",
        })
    if new_files > task.change_budget.max_new_files:
        violations.append({
            "code": "NEW_FILE_BUDGET_EXCEEDED",
            "path": "",
            "detail": f"{new_files} > {task.change_budget.max_new_files}",
        })
    if dependency_changes and not task.change_budget.allow_dependency_changes:
        for path in dependency_changes:
            violations.append({
                "code": "DEPENDENCY_CHANGE_FORBIDDEN",
                "path": path,
                "detail": "changeBudget.allowDependencyChanges=false",
            })

    verdict = "PASS" if not violations else "FAIL"
    return {
        "schemaVersion": "2.0",
        "taskId": task.task_id,
        "baseline": baseline,
        "verdict": verdict,
        "changedFiles": changed,
        "metrics": metrics,
        "dependencyChanges": dependency_changes,
        "changeBudget": {
            "maxChangedFiles": task.change_budget.max_changed_files,
            "maxAddedLines": task.change_budget.max_added_lines,
            "maxNewFiles": task.change_budget.max_new_files,
            "allowDependencyChanges": task.change_budget.allow_dependency_changes,
        },
        "simplicityPlan": {
            "selectedRung": task.simplicity.selected_rung,
            "rationale": task.simplicity.rationale,
            "considered": list(task.simplicity.considered),
        },
        "violations": violations,
    }
