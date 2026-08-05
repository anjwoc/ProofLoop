from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from proofloop_core.contracts.goal import build_goal_contract
from proofloop_core.context.memory import prepare_memory, write_memory
from proofloop_core.runtimes.runtime import RuntimeRegistry
from proofloop_core.contracts.task_brief import ChangeBudget, CheckSpec, SimplicityPlan, TaskBrief


class RuntimeGoalMemoryTest(unittest.TestCase):
    def test_goal_registry_routes_roles_across_available_runtimes(self) -> None:
        available = {"claude": "/bin/claude", "agy": "/bin/agy", "codex": "/bin/codex"}
        with patch("proofloop_core.runtime.shutil.which", side_effect=lambda name: available.get(name)), patch(
            "proofloop_core.runtime.acp_sdk_available", return_value=False
        ):
            registry = RuntimeRegistry()
            explorer = registry.resolve("codex", "explorer_fast", policy="goal")
            recovery = registry.resolve("codex", "implementer_recovery", policy="goal")
        self.assertEqual("claude-code", explorer.runtime_id)
        self.assertEqual("haiku", explorer.model)
        self.assertEqual("agy", recovery.runtime_id)
        self.assertEqual("gemini-3.1-pro-high", recovery.model)
        self.assertEqual("legacy-cli", recovery.transport)

    def test_codex_account_default_override_is_explicit_in_the_resolved_trace(self) -> None:
        with patch.dict("os.environ", {"PROOFLOOP_CODEX_MODEL": "CURRENT_ACCOUNT_DEFAULT"}), patch(
            "proofloop_core.runtime.shutil.which", return_value="/bin/codex"
        ), patch("proofloop_core.runtime.acp_sdk_available", return_value=False):
            resolved = RuntimeRegistry().resolve("codex", "implementer_fast")
        self.assertEqual("CURRENT_ACCOUNT_DEFAULT", resolved.model)
        self.assertEqual("codex", resolved.runtime_id)

    def test_claude_default_reviewer_uses_an_available_default_model(self) -> None:
        with patch("proofloop_core.runtime.shutil.which", return_value="/bin/claude"), patch(
            "proofloop_core.runtime.acp_sdk_available", return_value=False
        ):
            resolved = RuntimeRegistry().resolve("claude-code", "reviewer_deep")
        self.assertEqual("claude-code", resolved.runtime_id)
        self.assertEqual("opus", resolved.model)

    def test_goal_contract_and_two_tier_memory_are_bounded_and_safe(self) -> None:
        task = TaskBrief(
            task_id="TASK-001",
            objective="Implement the requested behavior",
            allowed_paths=("src/**",),
            protected_paths=(),
            required_checks=(CheckSpec(["python3", "-m", "unittest"], name="unit"),),
            change_budget=ChangeBudget(2, 20, 0, False),
            simplicity=SimplicityPlan(
                "DIRECT_CHANGE",
                "one change",
                ("REUSE_EXISTING", "STDLIB", "PLATFORM_NATIVE", "INSTALLED_DEPENDENCY"),
                ("fixture#/goal",),
                (),
            ),
            max_fast_attempts=1,
            max_recovery_attempts=0,
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
