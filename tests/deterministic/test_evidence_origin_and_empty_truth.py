from __future__ import annotations

import json
from pathlib import Path

from proofloop_core.assurance.truth import build_truth_report
from proofloop_core.contracts.run_policy import resolve_run_policy
from proofloop_core.contracts.run_state import create_invocation_context, start_run


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_start_run_records_cli_host_without_claiming_authentication(tmp_path: Path) -> None:
    policy = resolve_run_policy()
    context = create_invocation_context(
        tmp_path,
        policy,
        invocation_kind="CLI",
        requested_host="codex",
    )

    started = start_run(tmp_path, "Fix the bug", policy=policy, invocation_context=context)
    root = Path(started["runDir"])
    run = json.loads((root / "run.json").read_text(encoding="utf-8"))
    provenance = json.loads((root / "run-provenance.json").read_text(encoding="utf-8"))

    assert run["hostRequested"] == "codex"
    assert run["invocationKind"] == "CLI"
    assert provenance["requestedHost"] == "codex"
    assert provenance["invocationKind"] == "CLI"
    assert "authenticated" not in json.dumps(provenance).lower()


def test_programmatic_run_is_labelled_instead_of_looking_authenticated(tmp_path: Path) -> None:
    started = start_run(tmp_path, "Exercise mechanics")
    root = Path(started["runDir"])
    run = json.loads((root / "run.json").read_text(encoding="utf-8"))
    provenance = json.loads((root / "run-provenance.json").read_text(encoding="utf-8"))

    assert run["hostRequested"] is None
    assert run["invocationKind"] == "PROGRAMMATIC"
    assert provenance["requestedHost"] is None
    assert provenance["invocationKind"] == "PROGRAMMATIC"


def test_truth_rejects_empty_check_evidence_even_when_report_says_pass(tmp_path: Path) -> None:
    _write(tmp_path / "run.json", {"hostRequested": "codex", "invocationKind": "CLI"})
    _write(tmp_path / "run-provenance.json", {
        "invocationKind": "CLI",
        "requestedHost": "codex",
    })
    _write(tmp_path / "checks" / "checks.json", {"verdict": "PASS", "checks": []})
    _write(tmp_path / "diff-guard.json", {"verdict": "PASS"})
    _write(tmp_path / "review.json", {"verdict": "APPROVED"})
    _write(tmp_path / "model-trace-summary.json", {"routingClaimed": False, "routingObserved": False})

    truth = build_truth_report(tmp_path)

    assert truth["verdict"] == "FAILED"
    assert "CHECK_EVIDENCE_EMPTY" in truth["blockers"]
    assert truth["host"] == "codex"
    assert truth["evidenceOrigin"] == "CLI"
