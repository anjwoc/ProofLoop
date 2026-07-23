from __future__ import annotations

import json
import sys
from pathlib import Path

from proofloop_core.assurance.truth import build_truth_report
from proofloop_core.contracts.run_state import start_run


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_start_run_records_cli_host_without_claiming_authentication(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(sys, "argv", ["proofloop-core", "run", "--host", "codex"])

    started = start_run(tmp_path, "Fix the bug")
    run = json.loads((Path(started["runDir"]) / "run.json").read_text(encoding="utf-8"))

    assert run["host"] == "codex"
    assert run["evidenceOrigin"] == "CLI_HOST_RUN"


def test_programmatic_run_is_labelled_instead_of_looking_authenticated(
    tmp_path: Path, monkeypatch: object
) -> None:
    monkeypatch.setattr(sys, "argv", ["pytest"])
    for key in (
        "PROOFLOOP_HOST",
        "CODEX_THREAD_ID",
        "CODEX_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDECODE",
        "ANTIGRAVITY_SESSION_ID",
        "AGY_SESSION_ID",
    ):
        monkeypatch.delenv(key, raising=False)

    started = start_run(tmp_path, "Exercise mechanics")
    run = json.loads((Path(started["runDir"]) / "run.json").read_text(encoding="utf-8"))

    assert run["host"] == "unresolved"
    assert run["evidenceOrigin"] == "PROGRAMMATIC_OR_UNKNOWN"


def test_truth_rejects_empty_check_evidence_even_when_report_says_pass(tmp_path: Path) -> None:
    _write(tmp_path / "run.json", {"host": "codex", "evidenceOrigin": "CLI_HOST_RUN"})
    _write(tmp_path / "checks" / "checks.json", {"verdict": "PASS", "checks": []})
    _write(tmp_path / "diff-guard.json", {"verdict": "PASS"})
    _write(tmp_path / "review.json", {"verdict": "APPROVED"})
    _write(
        tmp_path / "model-trace-summary.json",
        {"routingClaimed": False, "routingObserved": False},
    )

    truth = build_truth_report(tmp_path)

    assert truth["verdict"] == "FAILED"
    assert "CHECK_EVIDENCE_EMPTY" in truth["blockers"]
    assert truth["host"] == "codex"
    assert truth["evidenceOrigin"] == "CLI_HOST_RUN"
