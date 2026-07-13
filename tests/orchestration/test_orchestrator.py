from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from proofloop_core.adapters import RoleInvocation
from proofloop_core.orchestrator import orchestrate


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def make_repo(root: Path) -> None:
    git(root, "init")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "value.py").write_text('def get_value():\n    return "broken"\n', encoding="utf-8")
    (root / "tests" / "test_value.py").write_text(
        "import unittest\n"
        "from src.value import get_value\n\n"
        "class ValueTest(unittest.TestCase):\n"
        "    def test_value(self):\n"
        "        self.assertEqual('fixed', get_value())\n\n"
        "if __name__ == '__main__':\n"
        "    unittest.main()\n",
        encoding="utf-8",
    )
    git(root, "add", ".")
    git(root, "commit", "-m", "baseline")


def load_events(run_dir: str | Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in (Path(run_dir) / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]


class ScriptedAdapter:
    host = "fake"

    def __init__(self, *, recovery: bool = False, omit_plan: bool = False, planner_mutates: bool = False, review_fix: bool = False):
        self.recovery = recovery
        self.review_fix = review_fix
        self.omit_plan = omit_plan
        self.planner_mutates = planner_mutates
        self.fast_calls = 0
        self.reviewer_calls = 0
        self.calls: list[str] = []

    def probe(self) -> dict[str, Any]:
        return {
            "host": "fake",
            "available": True,
            "mode": "EXTERNAL_MODEL_ROUTING",
            "modelRoutingStatus": "OBSERVABLE",
            "externalRoles": {
                "planner_deep": {"model": "deep-model"},
                "implementer_fast": {"model": "fast-model"},
                "implementer_recovery": {"model": "recovery-model"},
                "reviewer_deep": {"model": "deep-model"},
            },
        }

    def invoke(self, invocation: RoleInvocation) -> dict[str, Any]:
        self.calls.append(invocation.role)
        if invocation.role == "planner_deep":
            if self.planner_mutates:
                (invocation.repository / "src" / "value.py").write_text("# planner mutation\n", encoding="utf-8")
            if not self.omit_plan and invocation.result_path:
                invocation.result_path.parent.mkdir(parents=True, exist_ok=True)
                invocation.result_path.write_text(json.dumps({
                    "schemaVersion": "1.0",
                    "verdict": "READY",
                    "summary": "Fix the bounded value function.",
                    "tasks": [{
                        "id": "TASK-001",
                        "objective": "Return the expected fixed value.",
                        "allowedPaths": ["src/**", "tests/**"],
                        "protectedPaths": [],
                        "requiredChecks": [{
                            "name": "unit",
                            "command": [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                            "timeoutSeconds": 30,
                        }],
                        "changeBudget": {
                            "maxChangedFiles": 2,
                            "maxAddedLines": 20,
                            "maxNewFiles": 0,
                            "allowDependencyChanges": False,
                        },
                        "simplicity": {
                            "selectedRung": "DIRECT_CHANGE",
                            "rationale": "One existing function is wrong.",
                            "considered": ["Reuse the existing function and test"],
                        },
                        "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1},
                    }],
                }), encoding="utf-8")
            return self._result("planner_deep", "deep-model")

        if invocation.role == "implementer_fast":
            self.fast_calls += 1
            direct_bootstrap = invocation.task_path is None and invocation.result_path and invocation.result_path.name == "TASK-001.json"
            if not self.recovery or direct_bootstrap:
                (invocation.repository / "src" / "value.py").write_text('def get_value():\n    return "fixed"\n', encoding="utf-8")
            if invocation.result_path:
                invocation.result_path.parent.mkdir(parents=True, exist_ok=True)
                if direct_bootstrap:
                    invocation.result_path.write_text(json.dumps({
                        "id": "TASK-001",
                        "objective": "Return the expected fixed value.",
                        "allowedPaths": ["src/**", "tests/**"],
                        "protectedPaths": [],
                        "requiredChecks": [{"name": "unit", "command": [sys.executable, "-m", "unittest", "discover", "-s", "tests"], "timeoutSeconds": 30}],
                        "changeBudget": {"maxChangedFiles": 2, "maxAddedLines": 20, "maxNewFiles": 0, "allowDependencyChanges": False},
                        "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "one function", "considered": ["reuse existing"]},
                        "budgets": {"maxFastAttempts": 2, "maxRecoveryAttempts": 1},
                    }), encoding="utf-8")
                else:
                    invocation.result_path.write_text(json.dumps({"status": "DONE", "classification": "LOCAL_IMPLEMENTATION"}), encoding="utf-8")
            return self._result("implementer_fast", "fast-model")

        if invocation.role == "implementer_recovery":
            (invocation.repository / "src" / "value.py").write_text('def get_value():\n    return "fixed"\n', encoding="utf-8")
            if invocation.result_path:
                invocation.result_path.parent.mkdir(parents=True, exist_ok=True)
                invocation.result_path.write_text(json.dumps({"status": "DONE", "classification": "LOCAL_IMPLEMENTATION"}), encoding="utf-8")
            return self._result("implementer_recovery", "recovery-model")

        if invocation.role == "reviewer_deep":
            self.reviewer_calls += 1
            needs_fix = self.review_fix and self.reviewer_calls == 1
            if invocation.result_path:
                invocation.result_path.parent.mkdir(parents=True, exist_ok=True)
                invocation.result_path.write_text(json.dumps({
                    "verdict": "FIX_REQUIRED" if needs_fix else "APPROVED",
                    "simplicityVerdict": "OVERBUILT" if needs_fix else "MINIMAL",
                    "findings": [{"severity": "important", "message": "simplify final change"}] if needs_fix else [],
                    "deletionCandidates": ["unused abstraction"] if needs_fix else [],
                }), encoding="utf-8")
            return self._result("reviewer_deep", "deep-model")
        raise AssertionError(invocation.role)

    @staticmethod
    def _result(role: str, model: str) -> dict[str, Any]:
        return {
            "verdict": "PASS",
            "role": role,
            "requestedModel": model,
            "observedModel": model,
            "modelEvidence": "HOST_RESOLVED",
            "exitCode": 0,
            "traceRecorded": False,
        }


class OrchestratorTest(unittest.TestCase):
    """SIMULATED_ORCHESTRATION: role models are deterministic adapter fixtures."""

    def test_full_normal_loop_is_core_owned_and_proven(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            adapter = ScriptedAdapter()
            stream = io.StringIO()
            result = orchestrate(
                "codex",
                root,
                "Implement the bounded value behavior across source and tests",
                adapter=adapter,
                strategy_override="PLANNED_IMPLEMENTATION",
                stream=stream,
                output_format="jsonl",
            )
            self.assertEqual("PROVEN", result["verdict"], result)
            self.assertEqual(["planner_deep", "implementer_fast", "reviewer_deep"], adapter.calls)
            run = Path(result["runDir"])
            self.assertEqual("PROVEN", json.loads((run / "truth-report.json").read_text())["verdict"])
            self.assertTrue(json.loads((run / "model-trace-summary.json").read_text())["routingObserved"])
            self.assertIn('return "fixed"', (root / "src" / "value.py").read_text(encoding="utf-8"))
            events = load_events(run)
            types = [event["type"] for event in events]
            self.assertEqual("run.started", types[0])
            for required in (
                "capability.detected",
                "strategy.selected",
                "context.ready",
                "task.created",
                "task.started",
                "role.started",
                "role.model_observed",
                "check.completed",
                "diff_guard.completed",
                "attempt.recorded",
                "task.completed",
                "review.started",
                "review.completed",
                "truth.completed",
            ):
                self.assertIn(required, types)
            self.assertEqual("run.completed", types[-1])
            self.assertEqual(list(range(1, len(events) + 1)), [event["sequence"] for event in events])
            claims = [event for event in events if event["type"].startswith("claim.")]
            self.assertTrue(claims)
            self.assertTrue(all(event["type"] == "claim.supported" for event in claims))
            self.assertTrue(all(str(event["data"].get("status", "")).startswith("SUPPORTED") for event in claims))
            self.assertLess(max(events.index(event) for event in claims), types.index("truth.completed"))
            rendered = [json.loads(line) for line in stream.getvalue().splitlines()]
            self.assertEqual(events, rendered)

    def test_role_timeout_is_preserved_as_a_distinct_failure_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            adapter = ScriptedAdapter()

            def timeout_result(_invocation):
                return {
                    "verdict": "FAIL",
                    "role": "planner_deep",
                    "requestedModel": "deep-model",
                    "observedModel": None,
                    "modelEvidence": "CLI_REQUESTED_ONLY",
                    "exitCode": 124,
                    "timedOut": True,
                    "cancelled": False,
                    "traceRecorded": False,
                }

            adapter.invoke = timeout_result  # type: ignore[method-assign]
            result = orchestrate(
                "codex",
                root,
                "Implement the bounded value behavior",
                adapter=adapter,
                strategy_override="PLANNED_IMPLEMENTATION",
            )
            failed = next(event for event in load_events(result["runDir"]) if event["type"] == "role.failed")
            self.assertTrue(failed["data"]["timedOut"])
            self.assertFalse(failed["data"]["cancelled"])
            self.assertEqual("HOST_TIMEOUT", failed["data"]["reasonCode"])

    def test_role_cancellation_emits_a_distinct_terminal_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            adapter = ScriptedAdapter()

            def cancelled_result(_invocation):
                return {
                    "verdict": "FAIL",
                    "role": "planner_deep",
                    "requestedModel": "deep-model",
                    "observedModel": None,
                    "modelEvidence": "CLI_REQUESTED_ONLY",
                    "exitCode": 130,
                    "timedOut": False,
                    "cancelled": True,
                    "traceRecorded": False,
                }

            adapter.invoke = cancelled_result  # type: ignore[method-assign]
            result = orchestrate(
                "codex",
                root,
                "Implement the bounded value behavior",
                adapter=adapter,
                strategy_override="PLANNED_IMPLEMENTATION",
            )
            cancelled = next(event for event in load_events(result["runDir"]) if event["type"] == "role.cancelled")
            self.assertFalse(cancelled["data"]["timedOut"])
            self.assertTrue(cancelled["data"]["cancelled"])
            self.assertEqual("HOST_CANCELLED", cancelled["data"]["reasonCode"])

    def test_direct_strategy_skips_deep_planner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            adapter = ScriptedAdapter()
            result = orchestrate(
                "codex",
                root,
                "Fix this one-line local value bug",
                adapter=adapter,
                strategy_override="DIRECT_VERIFIED_CHANGE",
            )
            self.assertEqual("PROVEN", result["verdict"], result)
            self.assertEqual(["implementer_fast", "reviewer_deep"], adapter.calls)
            strategy = json.loads((Path(result["runDir"]) / "strategy.json").read_text())
            self.assertFalse(strategy["plannerRequired"])

    def test_repeated_fast_failure_invokes_recovery_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            adapter = ScriptedAdapter(recovery=True)
            result = orchestrate(
                "codex",
                root,
                "Implement the bounded value behavior across source and tests",
                adapter=adapter,
                strategy_override="PLANNED_IMPLEMENTATION",
            )
            self.assertEqual("PROVEN", result["verdict"], result)
            self.assertEqual(
                ["planner_deep", "implementer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep"],
                adapter.calls,
            )
            attempts = [json.loads(line) for line in (Path(result["runDir"]) / "attempts.jsonl").read_text().splitlines()]
            self.assertEqual(["implementer_fast", "implementer_fast", "implementer_recovery"], [item["role"] for item in attempts])
            self.assertEqual(attempts[0]["failureFingerprint"], attempts[1]["failureFingerprint"])
            transitions = (Path(result["runDir"]) / "transitions.jsonl").read_text()
            self.assertIn('"state": "RETRY_FAST"', transitions)
            self.assertIn('"state": "RUN_RECOVERY"', transitions)
            events = load_events(result["runDir"])
            types = [event["type"] for event in events]
            self.assertIn("retry.scheduled", types)
            self.assertIn("progress.stalled", types)
            recovery = next(event for event in events if event["type"] == "recovery.scheduled")
            self.assertEqual("implementer_fast", recovery["data"]["fromRole"])
            self.assertEqual("implementer_recovery", recovery["data"]["toRole"])
            self.assertEqual("fast-model", recovery["data"]["fromRequestedModel"])
            self.assertEqual("recovery-model", recovery["data"]["toRequestedModel"])
            self.assertEqual(attempts[1]["failureFingerprint"], recovery["data"]["fingerprint"])

    def test_review_fix_required_invokes_recovery_and_re_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            adapter = ScriptedAdapter(review_fix=True)
            result = orchestrate(
                "codex",
                root,
                "Implement the bounded value behavior",
                adapter=adapter,
                strategy_override="PLANNED_IMPLEMENTATION",
            )
            self.assertEqual("PROVEN", result["verdict"], result)
            self.assertEqual(
                ["planner_deep", "implementer_fast", "reviewer_deep", "implementer_recovery", "reviewer_deep"],
                adapter.calls,
            )
            run = Path(result["runDir"])
            final_review = json.loads((run / "review.json").read_text())
            self.assertEqual("APPROVED", final_review["verdict"])
            transitions = (run / "transitions.jsonl").read_text()
            self.assertIn('"state": "REVIEW_REPAIR"', transitions)
            events = load_events(run)
            fix = next(event for event in events if event["type"] == "review.fix_required")
            self.assertEqual("simplify final change", fix["data"]["finding"])
            self.assertTrue(
                any(
                    event["type"] == "recovery.scheduled"
                    and event["data"].get("reasonCode") == "REVIEW_FIX_REQUIRED"
                    and event["data"].get("fromRequestedModel") == "deep-model"
                    and event["data"].get("toRequestedModel") == "recovery-model"
                    for event in events
                )
            )

    def test_success_claim_without_plan_artifact_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            result = orchestrate(
                "codex",
                root,
                "Implement the bounded value behavior",
                adapter=ScriptedAdapter(omit_plan=True),
                strategy_override="PLANNED_IMPLEMENTATION",
            )
            self.assertEqual("BLOCKED", result["verdict"])
            self.assertEqual("PLAN_ARTIFACT_MISSING", result["code"])
            events = load_events(result["runDir"])
            self.assertEqual("run.blocked", events[-1]["type"])
            self.assertEqual("PLAN_ARTIFACT_MISSING", events[-1]["data"]["code"])


    def test_repository_analysis_blocks_instead_of_simulating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            adapter = ScriptedAdapter()
            result = orchestrate(
                "codex",
                root,
                "Analyze this repository without changing code",
                adapter=adapter,
                strategy_override="REPOSITORY_ANALYSIS",
            )
            self.assertEqual("BLOCKED", result["verdict"])
            self.assertEqual("ANALYSIS_ORCHESTRATION_NOT_IMPLEMENTED", result["code"])
            self.assertEqual([], adapter.calls)

    def test_planner_source_mutation_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_repo(root)
            result = orchestrate(
                "codex",
                root,
                "Implement the bounded value behavior",
                adapter=ScriptedAdapter(planner_mutates=True),
                strategy_override="PLANNED_IMPLEMENTATION",
            )
            self.assertEqual("FAILED", result["verdict"])
            self.assertEqual("PLANNER_DEEP_MUTATED_SOURCE", result["code"])
            events = load_events(result["runDir"])
            self.assertEqual("run.failed", events[-1]["type"])


if __name__ == "__main__":
    unittest.main()
