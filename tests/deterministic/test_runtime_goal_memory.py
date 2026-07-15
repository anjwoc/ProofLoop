from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofloop_core.goal import GoalFSM, build_goal_contract
from proofloop_core.memory import prepare_memory, write_memory
from proofloop_core.runtime import RuntimeRegistry
from proofloop_core.task_brief import ChangeBudget, CheckSpec, SimplicityPlan, TaskBrief


class RuntimeGoalMemoryTest(unittest.TestCase):
    def test_goal_registry_routes_roles_across_available_runtimes(self) -> None:
        available = {
            "claude": "/bin/claude",
            "gemini": "/bin/gemini",
            "codex": "/bin/codex",
        }
        with patch("proofloop_core.runtime.shutil.which", side_effect=lambda name: available.get(name)), patch(
            "proofloop_core.runtime.acp_sdk_available", return_value=False
        ):
            registry = RuntimeRegistry()
            explorer = registry.resolve("codex", "explorer_fast", policy="goal")
            recovery = registry.resolve("codex", "implementer_recovery", policy="goal")

        self.assertEqual("claude-code", explorer.runtime_id)
        self.assertEqual("haiku", explorer.model)
        self.assertEqual("gemini", recovery.runtime_id)
        self.assertEqual("gemini-3.1-pro-preview", recovery.model)
        self.assertEqual("legacy-cli", recovery.transport)

    def test_goal_fsm_rejects_illegal_transition_and_persists_legal_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            machine = GoalFSM(tmp)
            with self.assertRaisesRegex(ValueError, "illegal goal transition"):
                machine.transition("CONVERGED", reason="no evidence")
            for state in ("EXPLORE", "DESIGN", "IMPLEMENT", "VERIFY", "DEEP_REVIEW", "CONVERGED"):
                machine.transition(state, reason="test")
            current = json.loads((Path(tmp) / "goal-state.json").read_text(encoding="utf-8"))
            self.assertEqual("CONVERGED", current["state"])
            self.assertEqual(6, len((Path(tmp) / "goal-transitions.jsonl").read_text().splitlines()))

    def test_goal_contract_and_two_tier_memory_are_bounded_and_safe(self) -> None:
        task = TaskBrief(
            task_id="TASK-001",
            objective="Implement the requested behavior",
            allowed_paths=("src/**",),
            protected_paths=(),
            required_checks=(CheckSpec(["python3", "-m", "unittest"], name="unit"),),
            change_budget=ChangeBudget(2, 20, 0, False),
            simplicity=SimplicityPlan("DIRECT_CHANGE", "one change", ("reuse",)),
        )
        contract = build_goal_contract("Fix behavior", [task])
        self.assertEqual("SC-REQUEST", contract.criteria[0].criterion_id)
        self.assertTrue(any(item.evidence_kind == "COMMAND_EXIT" for item in contract.criteria))

        with tempfile.TemporaryDirectory() as tmp:
            context = prepare_memory(tmp, "TASK-001")
            write_memory(context.task_path, "## Cycle 1\n\n- PASS", append=True)
            self.assertIn("Cycle 1", context.task_path.read_text(encoding="utf-8"))
            self.assertNotEqual(context.workflow_path, context.task_path)
            with self.assertRaisesRegex(ValueError, "safe path segment"):
                prepare_memory(tmp, "../escape")


if __name__ == "__main__":
    unittest.main()
