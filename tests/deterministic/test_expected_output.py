from __future__ import annotations

import json
from pathlib import Path

from proofloop_core.contracts.expected_output import verify_expected_output, write_expected_output_report
from proofloop_core.contracts.request_envelope import hash_raw_text


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _event(event_type: str) -> dict[str, object]:
    return {"type": event_type}


def _make_observable_run(tmp_path: Path, *, authority: str = "read_only") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    run = repo / ".proofloop" / "runs" / "run-1"
    run.mkdir(parents=True)
    raw = "inspect the payment retry boundary"
    _write_json(run / "run.json", {"runId": "run-1", "repository": str(repo)})
    _write_json(run / "request.json", {"request": raw})
    _write_json(
        run / "request-envelope.json",
        {"requestId": "run-1", "rawText": raw, "rawHash": hash_raw_text(raw), "repoRoot": str(repo)},
    )
    _write_json(
        run / "intent-gate.json",
        {"intentKind": "audit", "clarity": "groundable", "authority": authority, "groundingRequired": True},
    )
    _write_json(
        run / "intent-contract.json",
        {"originalRequest": raw, "objective": "Inspect retry behavior", "acceptanceCriteria": [{"id": "AC-1"}], "authorizationBoundary": "Read only"},
    )
    _write_json(run / "grounding-snapshot.json", {"requestId": "run-1", "repoRoot": str(repo), "detectedCommands": {}})
    _write_json(run / "strategy.json", {"tier": "T1", "strategy": "REPOSITORY_ANALYSIS"})
    _write_json(
        run / "refined-request-shadow.json",
        {"objective": {"statement": "Inspect retry behavior"}, "acceptanceCriteria": [{"id": "AC-1"}], "scope": {}},
    )
    event_types = (
        "run.started", "request.envelope_created", "intent_gate.started", "intent_gate.completed",
        "grounding.started", "grounding.completed", "strategy.selected",
    )
    (run / "events.jsonl").write_text("\n".join(json.dumps(_event(item)) for item in event_types) + "\n", encoding="utf-8")
    return run


def test_in_progress_run_has_a_traceable_user_experience(tmp_path: Path) -> None:
    run = _make_observable_run(tmp_path)

    report = verify_expected_output(run, expected_repository=tmp_path / "repo")

    assert report["status"] == "IN_PROGRESS"
    assert report["failures"] == []


def test_repository_root_mismatch_fails_instead_of_accepting_a_nested_request_directory(tmp_path: Path) -> None:
    run = _make_observable_run(tmp_path)

    report = verify_expected_output(run, expected_repository=tmp_path / "another-repository")

    assert report["status"] == "FAIL"
    assert "repository_binding" in report["failures"]


def test_terminal_audit_needs_a_visible_truth_verdict(tmp_path: Path) -> None:
    run = _make_observable_run(tmp_path)
    events = (run / "events.jsonl").read_text(encoding="utf-8")
    terminal_events = [_event("verdict.issued"), _event("truth.completed"), _event("run.completed")]
    (run / "events.jsonl").write_text(events + "".join(json.dumps(e) + "\n" for e in terminal_events), encoding="utf-8")
    _write_json(run / "truth-report.json", {"verdict": "PROVEN"})

    report = write_expected_output_report(run, expected_repository=tmp_path / "repo", require_terminal=True)

    assert report["status"] == "PASS"
    assert (run / "expected-output-report.json").is_file()


def test_terminal_run_without_truth_evidence_is_not_accepted(tmp_path: Path) -> None:
    run = _make_observable_run(tmp_path)

    report = verify_expected_output(run, expected_repository=tmp_path / "repo", require_terminal=True)

    assert report["status"] == "FAIL"
    assert "evidence_backed_truth_verdict" in report["failures"]


def test_private_reasoning_in_a_host_log_fails_the_observable_contract(tmp_path: Path) -> None:
    run = _make_observable_run(tmp_path)
    transcript = run / "invocations" / "role-1" / "stdout.log"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        '{"type":"assistant","message":{"content":[{"type":"thinking","thinking":"private"}]}}\n',
        encoding="utf-8",
    )

    report = verify_expected_output(run, expected_repository=tmp_path / "repo")

    assert report["status"] == "FAIL"
    assert "private_reasoning_redacted" in report["failures"]


def test_redacted_thinking_marker_is_safe_to_persist_for_audit(tmp_path: Path) -> None:
    run = _make_observable_run(tmp_path)
    transcript = run / "invocations" / "role-1" / "stdout.log"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"type":"thinking","redacted":true}\n', encoding="utf-8")

    report = verify_expected_output(run, expected_repository=tmp_path / "repo")

    assert report["status"] == "IN_PROGRESS"
    assert "private_reasoning_redacted" not in report["failures"]
