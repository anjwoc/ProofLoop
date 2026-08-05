from proofloop_core.context.io import read_json, write_json
from proofloop_core.contracts.expected_output import write_run_outcome


def test_run_outcome_projects_existing_truth_without_promoting_it(tmp_path):
    write_json(tmp_path / "run.json", {"runId": "run-1"})
    write_json(
        tmp_path / "intent-contract.json",
        {"objective": "repair the flow", "acceptanceCriteria": [{"id": "AC-1", "criterion": "tests pass"}]},
    )
    write_json(tmp_path / "strategy.json", {"strategy": "PLANNED_IMPLEMENTATION", "tier": "T2"})
    truth = {
        "verdict": "PARTIAL",
        "blockers": [],
        "unproven": ["MODEL_ROUTING_UNPROVEN"],
        "evidence": {"checks": "checks/checks.json"},
    }

    outcome = write_run_outcome(tmp_path, truth, usage={"totals": {"rawTotal": 12}})

    assert outcome["verdict"] == "PARTIAL"
    assert outcome["unproven"] == ["MODEL_ROUTING_UNPROVEN"]
    assert outcome["strategy"] == {"name": "PLANNED_IMPLEMENTATION", "tier": "T2"}
    assert read_json(tmp_path / "run-outcome.json") == outcome


def test_run_outcome_keeps_terminal_failure_reason(tmp_path):
    write_json(tmp_path / "run.json", {"runId": "run-2"})
    truth = {"verdict": "FAILED", "blockers": ["CHECKS_FAILED"], "unproven": [], "evidence": {}}

    outcome = write_run_outcome(tmp_path, truth, message="verification failed")

    assert outcome["verdict"] == "FAILED"
    assert outcome["summary"] == "verification failed"
    assert outcome["blockers"] == ["CHECKS_FAILED"]
