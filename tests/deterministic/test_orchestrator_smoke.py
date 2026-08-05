from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

from proofloop_core.engine import intent_gate
from proofloop_core.engine.intent_gate import evaluate_intent
from proofloop_core.engine.orchestrator import run_proofloop


class DirectChangeAdapter:
    def probe(self) -> dict[str, object]:
        return {"host": "test", "available": True, "mode": "ROLE_ROUTING_ONLY"}

    def invoke(self, invocation: object) -> dict[str, object]:
        role = getattr(invocation, "role")
        if role == "classifier_fast":
            return {
                "verdict": "PASS",
                "stdout": json.dumps(
                    {
                        "intent_kind": "mutate",
                        "authority": "repository_mutation",
                        "clarity": "clear",
                        "injection_risk": "none",
                    }
                ),
            }
        repository = getattr(invocation, "repository")
        result_path = getattr(invocation, "result_path")
        assert result_path is not None
        result_path.parent.mkdir(parents=True, exist_ok=True)
        if role == "implementer_fast":
            (repository / "src" / "value.py").write_text(
                'def get_value():\n    return "fixed"\n',
                encoding="utf-8",
            )
            result_path.write_text(
                json.dumps(
                    {
                        "status": "DONE",
                        "classification": "LOCAL_IMPLEMENTATION",
                        "summary": "Updated the bounded function.",
                    }
                ),
                encoding="utf-8",
            )
            return {
                "verdict": "PASS",
                "role": role,
                "requestedModel": "test",
                "observedModel": "test",
                "modelEvidence": "TEST",
                "exitCode": 0,
                "traceRecorded": False,
            }

        result_path.write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "verdict": "READY",
                    "summary": "Fix the bounded value function.",
                    "tasks": [
                        {
                            "id": "TASK-001",
                            "objective": "Return the expected value.",
                            "criterion_ids": ["AC-001"],
                            "allowedPaths": ["src/**"],
                            "protectedPaths": [],
                            "requiredChecks": [{"name": "unit", "command": [sys.executable, "-m", "unittest", "discover", "-s", "tests"], "timeoutSeconds": 30}],
                            "changeBudget": {"maxChangedFiles": 1, "maxAddedLines": 2, "maxNewFiles": 0, "allowDependencyChanges": False},
                            "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "one existing function", "considered": ["reuse existing function"]},
                            "proofPlan": {"baselineChecks": [], "redChecks": [], "automatedChecks": [{"name": "unit-proof", "command": [sys.executable, "-m", "unittest", "discover", "-s", "tests"], "timeoutSeconds": 30}], "surfaceScenarios": [], "adversarialChecks": [], "cleanupChecks": []},
                            "budgets": {"maxFastAttempts": 1, "maxRecoveryAttempts": 0},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return {"verdict": "PASS", "role": role, "requestedModel": "test", "observedModel": "test", "modelEvidence": "TEST", "exitCode": 0, "traceRecorded": False}


class OversizedThenProviderBlockedAdapter(DirectChangeAdapter):
    def __init__(self) -> None:
        self.implementer_calls = 0

    def invoke(self, invocation: object) -> dict[str, object]:
        role = getattr(invocation, "role")
        if role != "implementer_fast":
            return super().invoke(invocation)
        self.implementer_calls += 1
        if self.implementer_calls == 2:
            return {
                "verdict": "BLOCKED",
                "role": role,
                "requestedModel": "test",
                "observedModel": None,
                "modelEvidence": "CLI_REQUESTED_ONLY",
                "exitCode": 1,
                "timedOut": True,
                "reasonCode": "HOST_PROVIDER_RESPONSE_TIMEOUT",
                "reason": "simulated provider response timeout",
                "traceRecorded": False,
            }
        repository = getattr(invocation, "repository")
        result_path = getattr(invocation, "result_path")
        assert result_path is not None
        (repository / "src" / "value.py").write_text(
            "\n".join(f"VALUE_{index} = {index}" for index in range(1600)) + "\n",
            encoding="utf-8",
        )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {"status": "DONE", "classification": "LOCAL_IMPLEMENTATION", "summary": "oversized"}
            ),
            encoding="utf-8",
        )
        return {
            "verdict": "PASS",
            "role": role,
            "requestedModel": "test",
            "observedModel": "test",
            "modelEvidence": "TEST",
            "exitCode": 0,
            "traceRecorded": False,
        }


class VerificationFailureAdapter(DirectChangeAdapter):
    """Returns a completed implementation whose Core-owned test still fails."""

    def __init__(self, classification: str = "LOCAL_IMPLEMENTATION") -> None:
        self.implementer_calls = 0
        self.classification = classification

    def invoke(self, invocation: object) -> dict[str, object]:
        role = getattr(invocation, "role")
        if role != "implementer_fast":
            return super().invoke(invocation)
        self.implementer_calls += 1
        result_path = getattr(invocation, "result_path")
        assert result_path is not None
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "status": "DONE",
                    "classification": self.classification,
                    "summary": "The adapter deliberately left the failing behavior unchanged.",
                }
            ),
            encoding="utf-8",
        )
        return {
            "verdict": "PASS",
            "role": role,
            "requestedModel": "test",
            "observedModel": "test",
            "modelEvidence": "TEST",
            "exitCode": 0,
            "traceRecorded": False,
        }


class NoResultAdapter(DirectChangeAdapter):
    """Simulates a host that returns prose with exit code zero but no result envelope."""

    def invoke(self, invocation: object) -> dict[str, object]:
        role = getattr(invocation, "role")
        if role != "implementer_fast":
            return super().invoke(invocation)
        return {
            "verdict": "PASS",
            "role": role,
            "requestedModel": "test",
            "observedModel": "test",
            "modelEvidence": "TEST",
            "exitCode": 0,
            "traceRecorded": False,
        }


class OwnerDecisionAdapter:
    def probe(self) -> dict[str, object]:
        return {"host": "test", "available": True, "mode": "ROLE_ROUTING_ONLY"}

    def invoke(self, invocation: object) -> dict[str, object]:
        assert getattr(invocation, "role") == "classifier_fast"
        return {
            "verdict": "PASS",
            "stdout": json.dumps(
                {
                    "intent_kind": "mutate",
                    "authority": "repository_mutation",
                    "clarity": "owner_decision_required",
                    "injection_risk": "none",
                    "owner_question": "데이터 보존과 마이그레이션 중 무엇을 우선할까요?",
                }
            ),
        }


class CrashingProbeAdapter:
    def invoke(self, invocation: object) -> dict[str, object]:
        assert getattr(invocation, "role") == "classifier_fast"
        return {
            "verdict": "PASS",
            "stdout": json.dumps(
                {
                    "intent_kind": "mutate",
                    "authority": "repository_mutation",
                    "clarity": "clear",
                    "injection_risk": "none",
                }
            ),
        }

    def probe(self) -> dict[str, object]:
        raise RuntimeError("simulated ProofLoop adapter defect")


class InvalidPlannerAdapter:
    def probe(self) -> dict[str, object]:
        return {"host": "test", "available": True, "mode": "ROLE_ROUTING_ONLY"}

    def invoke(self, invocation: object) -> dict[str, object]:
        role = getattr(invocation, "role")
        if role == "classifier_fast":
            return {
                "verdict": "PASS",
                "stdout": json.dumps(
                    {
                        "intent_kind": "mutate",
                        "authority": "repository_mutation",
                        "clarity": "clear",
                        "injection_risk": "none",
                    }
                ),
            }
        result_path = getattr(invocation, "result_path")
        assert role == "planner_deep"
        assert result_path is not None
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "verdict": "READY",
                    "summary": "invalid empty plan",
                    "tasks": [],
                }
            ),
            encoding="utf-8",
        )
        return {
            "verdict": "PASS",
            "role": role,
            "requestedModel": "test",
            "observedModel": "test",
            "modelEvidence": "TEST",
            "exitCode": 0,
            "traceRecorded": False,
        }


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_direct_adaptive_run_reaches_truth_gate(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "value.py").write_text('def get_value():\n    return "broken"\n', encoding="utf-8")
    (tmp_path / "tests" / "test_value.py").write_text(
        "import unittest\n\n"
        "from src.value import get_value\n\n"
        "class ValueTest(unittest.TestCase):\n"
        "    def test_value(self):\n"
        '        self.assertEqual(get_value(), "fixed")\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    result = run_proofloop(
        "test",
        tmp_path,
        "Fix the one-line local value bug.",
        mode="adaptive",
        adapter=DirectChangeAdapter(),
        strategy_override="DIRECT_VERIFIED_CHANGE",
    )

    assert result["verdict"] == "PROVEN"
    run_dir = Path(result["runDir"])
    review = json.loads((run_dir / "review.json").read_text(encoding="utf-8"))
    assert review["reviewMode"] == "DETERMINISTIC_FAST_LANE"
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    event_types = [item["type"] for item in events]
    contract_index = event_types.index("contract.frozen")
    sandbox_index = event_types.index("sandbox.created")
    implementer_index = next(
        index
        for index, item in enumerate(events)
        if item["type"] == "role.started"
        and item["data"].get("role") == "implementer_fast"
    )
    assert contract_index < implementer_index
    assert sandbox_index < implementer_index < event_types.index("sandbox.promoted")
    sandbox_event = events[sandbox_index]
    assert not Path(sandbox_event["data"]["workspace"]).exists()
    assert next(item for item in events if item["type"] == "intent.compiled")["data"]["basis"]
    assert next(item for item in events if item["type"] == "strategy.selected")["data"]["basis"]
    assert next(item for item in events if item["type"] == "implementation.started")["data"]["basis"]
    changed = next(item for item in events if item["type"] == "implementation.changed")
    assert changed["data"]["changedPaths"] == ["src/value.py"]
    assert changed["data"]["diffGuardRef"]
    truth = next(item for item in events if item["type"] == "truth.completed")
    assert truth["data"]["changedFiles"] == 1
    assert truth["data"]["checksPassed"] == truth["data"]["checksTotal"] == 2
    assert truth["data"]["evidenceRefs"]
    assert (tmp_path / "src" / "value.py").read_text(encoding="utf-8") == (
        'def get_value():\n    return "fixed"\n'
    )


def test_contract_violation_does_not_spend_a_recovery_call(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "value.py").write_text("VALUE = 0\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    adapter = OversizedThenProviderBlockedAdapter()
    result = run_proofloop(
        "test",
        tmp_path,
        "Update src/value.py",
        mode="adaptive",
        adapter=adapter,
        strategy_override="DIRECT_VERIFIED_CHANGE",
    )

    run_dir = Path(result["runDir"])
    assert result["verdict"] == "FAILED"
    assert result["code"] == "TASK_CONTRACT_VIOLATION"
    assert "ADDED_LINE_BUDGET_EXCEEDED" in result["message"]
    assert "No automatic model retry was started" in result["message"]
    assert adapter.implementer_calls == 1
    assert (run_dir / "task-runs" / "TASK-001" / "attempt-01-diff-guard.json").is_file()
    assert not (tmp_path / "src" / "value.py").read_text(encoding="utf-8").startswith("VALUE_1")


def test_failed_core_check_is_failed_without_a_second_model_call(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "value.py").write_text('def get_value():\n    return "broken"\n', encoding="utf-8")
    (tmp_path / "tests" / "test_value.py").write_text(
        "import unittest\n\n"
        "from src.value import get_value\n\n"
        "class ValueTest(unittest.TestCase):\n"
        "    def test_value(self):\n"
        '        self.assertEqual(get_value(), "fixed")\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    adapter = VerificationFailureAdapter()
    result = run_proofloop(
        "test",
        tmp_path,
        "Fix the bounded value behavior.",
        mode="adaptive",
        adapter=adapter,
        strategy_override="PLANNED_IMPLEMENTATION",
    )

    assert result["verdict"] == "FAILED"
    assert result["code"] == "TASK_VERIFICATION_FAILED"
    assert "No automatic model retry was started" in result["message"]
    assert adapter.implementer_calls == 1


def test_spec_ambiguity_after_a_real_failed_check_requests_owner_input(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "value.py").write_text('def get_value():\n    return "broken"\n', encoding="utf-8")
    (tmp_path / "tests" / "test_value.py").write_text(
        "import unittest\n\n"
        "from src.value import get_value\n\n"
        "class ValueTest(unittest.TestCase):\n"
        "    def test_value(self):\n"
        '        self.assertEqual(get_value(), "fixed")\n',
        encoding="utf-8",
    )
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    adapter = VerificationFailureAdapter("SPEC_AMBIGUITY")
    result = run_proofloop(
        "test",
        tmp_path,
        "Fix the bounded value behavior.",
        mode="adaptive",
        adapter=adapter,
        strategy_override="PLANNED_IMPLEMENTATION",
    )

    assert result["verdict"] == "NEEDS_INPUT"
    assert result["code"] == "TASK_INPUT_REQUIRED"
    assert adapter.implementer_calls == 1
    assert "성공 조건" in result["questions"][0]


def test_zero_exit_without_a_role_result_is_failed_not_claimed_as_completion(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "value.py").write_text('def get_value():\n    return "broken"\n', encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    result = run_proofloop(
        "test",
        tmp_path,
        "Fix the bounded value behavior.",
        mode="adaptive",
        adapter=NoResultAdapter(),
        strategy_override="DIRECT_VERIFIED_CHANGE",
    )

    assert result["verdict"] == "FAILED"
    assert result["code"] == "ROLE_RESULT_MISSING"
    assert "broken" in (tmp_path / "src" / "value.py").read_text(encoding="utf-8")


def test_owner_decision_pauses_for_input_instead_of_claiming_blocked(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    stream = io.StringIO()
    result = run_proofloop(
        "test",
        tmp_path,
        "데이터 구조를 변경해줘.",
        mode="adaptive",
        adapter=OwnerDecisionAdapter(),
        stream=stream,
        color="never",
    )

    run_dir = Path(result["runDir"])
    assert result["verdict"] == "NEEDS_INPUT"
    assert result["questions"] == ["데이터 보존과 마이그레이션 중 무엇을 우선할까요?"]
    assert not (run_dir / "truth-report.json").exists()
    assert (run_dir / "input-request.json").is_file()
    assert "[ProofLoop][INPUT] 사용자 답변이 필요합니다." in stream.getvalue()




def test_internal_error_does_not_issue_a_truth_verdict(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    result = run_proofloop(
        "test",
        tmp_path,
        "Update README.md.",
        mode="adaptive",
        adapter=CrashingProbeAdapter(),
    )

    run_dir = Path(result["runDir"])
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result["verdict"] == "FAILED"
    assert result["failureDomain"] == "PROOFLOOP"
    assert (run_dir / "run-error.json").is_file()
    assert not (run_dir / "truth-report.json").exists()
    assert "run.failed" in [item["type"] for item in events]
    assert "verdict.issued" not in [item["type"] for item in events]


def test_invalid_planner_contract_is_a_proofloop_error_not_a_truth_verdict(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline")

    result = run_proofloop(
        "test",
        tmp_path,
        "Improve the repository behavior.",
        mode="adaptive",
        adapter=InvalidPlannerAdapter(),
        strategy_override="DIRECT_VERIFIED_CHANGE",
    )

    run_dir = Path(result["runDir"])
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert result["verdict"] == "FAILED"
    assert result["failureDomain"] == "PROOFLOOP"
    assert result["code"] == "PLAN_TASK_COUNT_INVALID"
    assert (run_dir / "run-error.json").is_file()
    assert not (run_dir / "truth-report.json").exists()
    assert "verdict.issued" not in [item["type"] for item in events]


def test_injected_adapter_never_falls_back_to_external_intent_cli(tmp_path: Path, monkeypatch: object) -> None:
    class FailingAdapter:
        def invoke(self, invocation: object) -> dict[str, object]:
            raise RuntimeError("offline test adapter")

    calls: list[str] = []
    monkeypatch.setattr(intent_gate, "_classify_with_cli", lambda request_text, host: calls.append(host))

    result = evaluate_intent("Fix a local bug.", adapter=FailingAdapter(), run_dir=tmp_path, repo=tmp_path)

    assert result.authority.value == "repository_mutation"
    assert calls == []
