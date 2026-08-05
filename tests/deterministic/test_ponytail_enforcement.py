from __future__ import annotations

import subprocess

import pytest

from proofloop_core.assurance.diff_guard import inspect_diff
from proofloop_core.contracts.task_brief import (
    ChangeBudget,
    SimplicityPlan,
    TaskBrief,
    load_task_brief,
)
from proofloop_core.context.io import write_json


def _git(repo, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "proofloop@example.test")
    _git(repo, "config", "user.name", "ProofLoop Test")
    (repo / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "app.py")
    _git(repo, "commit", "-m", "baseline")
    return repo


def _task(*, permitted: tuple[str, ...] = ()) -> TaskBrief:
    return TaskBrief(
        task_id="TASK-001",
        objective="make a bounded change",
        allowed_paths=("app.py", "helper.py"),
        protected_paths=(),
        required_checks=(),
        change_budget=ChangeBudget(
            max_changed_files=2,
            max_added_lines=None,
            max_new_files=1,
            allow_dependency_changes=False,
        ),
        simplicity=SimplicityPlan(
            selected_rung="MINIMAL_NEW_CODE",
            rationale="the explicit helper is required",
            considered=("REUSE_EXISTING", "STDLIB", "PLATFORM_NATIVE", "INSTALLED_DEPENDENCY"),
            evidence_refs=("repository-context.json#/facts/0",),
            permitted_new_artifacts=permitted,
        ),
        max_fast_attempts=1,
        max_recovery_attempts=0,
    )


def test_loader_rejects_new_code_without_ponytail_evidence(tmp_path) -> None:
    path = tmp_path / "task.json"
    write_json(path, {
        "id": "TASK-001",
        "objective": "add helper",
        "allowedPaths": ["helper.py"],
        "protectedPaths": [],
        "requiredChecks": [],
        "changeBudget": {
            "maxChangedFiles": 1,
            "maxAddedLines": None,
            "maxNewFiles": 1,
            "allowDependencyChanges": False,
        },
        "simplicity": {
            "selectedRung": "MINIMAL_NEW_CODE",
            "rationale": "needed",
            "considered": ["REUSE_EXISTING"],
            "permittedNewArtifacts": ["helper.py"],
        },
        "budgets": {"maxFastAttempts": 1, "maxRecoveryAttempts": 0},
    })

    with pytest.raises(ValueError, match="evidenceRefs"):
        load_task_brief(path)


def test_unplanned_new_file_fails_diff_guard(tmp_path) -> None:
    repo = _repo(tmp_path)
    baseline = _git(repo, "rev-parse", "HEAD")
    (repo / "helper.py").write_text("def helper():\n    return 1\n", encoding="utf-8")

    report = inspect_diff(_task(), repo, baseline)

    assert report["verdict"] == "FAIL"
    assert any(item["code"] == "UNJUSTIFIED_NEW_ARTIFACT" for item in report["violations"])
    assert report["semanticApproval"] == "UNPROVEN"


def test_explicitly_permitted_new_file_passes_scope_only(tmp_path) -> None:
    repo = _repo(tmp_path)
    baseline = _git(repo, "rev-parse", "HEAD")
    (repo / "helper.py").write_text("def helper():\n    return 1\n", encoding="utf-8")

    report = inspect_diff(_task(permitted=("helper.py",)), repo, baseline)

    assert report["verdict"] == "PASS"
    assert report["scopeStatus"] == "SCOPE_COMPLIANT"
    assert report["semanticApproval"] == "UNPROVEN"
