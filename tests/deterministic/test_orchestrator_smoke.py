from __future__ import annotations

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
        if getattr(invocation, "role") == "classifier_fast":
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
        (repository / "src" / "value.py").write_text('def get_value():\n    return "fixed"\n', encoding="utf-8")
        assert result_path is not None
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(
            json.dumps(
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
            ),
            encoding="utf-8",
        )
        return {"verdict": "PASS", "role": "implementer_fast", "requestedModel": "test", "observedModel": "test", "modelEvidence": "TEST", "exitCode": 0, "traceRecorded": False}


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
        "from src.value import get_value\n\n"
        "def test_value():\n"
        '    assert get_value() == "fixed"\n',
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
    review = json.loads((Path(result["runDir"]) / "review.json").read_text(encoding="utf-8"))
    assert review["reviewMode"] == "DETERMINISTIC_FAST_LANE"


def test_injected_adapter_never_falls_back_to_external_intent_cli(tmp_path: Path, monkeypatch: object) -> None:
    class FailingAdapter:
        def invoke(self, invocation: object) -> dict[str, object]:
            raise RuntimeError("offline test adapter")

    calls: list[str] = []
    monkeypatch.setattr(intent_gate, "_classify_with_cli", lambda request_text, host: calls.append(host))

    result = evaluate_intent("Fix a local bug.", adapter=FailingAdapter(), run_dir=tmp_path, repo=tmp_path)

    assert result.authority.value == "repository_mutation"
    assert calls == []
