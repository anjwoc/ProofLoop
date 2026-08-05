from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from proofloop_core.context.grounding import CommandCatalog
from proofloop_core.contracts.task_brief import ChangeBudget, CheckSpec, SimplicityPlan, TaskBrief
from proofloop_core.contracts.verification_plan import (
    authoritative_passed_criteria,
    compile_verification_plan,
    normalize_command,
    with_mandatory_checks,
)


def _task(command: list[str]) -> TaskBrief:
    return TaskBrief(
        task_id="TASK-001",
        objective="fix behavior",
        allowed_paths=("src/**",),
        protected_paths=(),
        required_checks=(CheckSpec(command=command, name="proposed"),),
        change_budget=ChangeBudget(2, 20, 0, False),
        simplicity=SimplicityPlan(
            "DIRECT_CHANGE",
            "bounded",
            ("REUSE_EXISTING", "STDLIB", "PLATFORM_NATIVE", "INSTALLED_DEPENDENCY"),
            ("fixture#/verification-plan",),
            (),
        ),
        max_fast_attempts=1,
        max_recovery_attempts=0,
        criterion_ids=("AC-001",),
    )


class VerificationPlanTest(unittest.TestCase):
    def test_python_executable_paths_normalize_to_same_command(self) -> None:
        self.assertEqual(
            normalize_command([sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
            normalize_command(["python3", "-m", "unittest", "discover", "-s", "tests"]),
        )

    def test_model_only_trivial_check_is_not_authoritative(self) -> None:
        plan = compile_verification_plan(
            criterion_ids=("AC-001",),
            tasks=(_task([sys.executable, "-c", "print('1 passed')"]),),
            command_catalog=CommandCatalog(
                tests=("python3 -m unittest discover -s tests",),
                lint=(),
                typecheck=(),
                build=(),
            ),
        )
        self.assertEqual("MODEL_PROPOSED", plan["candidateChecks"][0]["source"])
        self.assertEqual("MODEL_CLAIM", plan["candidateChecks"][0]["authority"])
        aggregate = with_mandatory_checks(_task([sys.executable, "-c", "print('1 passed')"]), plan)
        self.assertEqual(2, len(aggregate.required_checks))
        self.assertIsNone(aggregate.required_checks[1].timeout_seconds)

    def test_only_passing_mandatory_core_checks_close_criteria(self) -> None:
        command = ["python3", "-m", "unittest", "discover", "-s", "tests"]
        plan = compile_verification_plan(
            criterion_ids=("AC-001",),
            tasks=(_task(command),),
            command_catalog=CommandCatalog(("python3 -m unittest discover -s tests",), (), (), ()),
        )
        fake_only = {"checks": [{"command": [sys.executable, "-c", "pass"], "status": "PASS"}]}
        core_pass = {"checks": [{"command": command, "status": "PASS"}]}
        self.assertEqual(set(), authoritative_passed_criteria(plan, fake_only))
        self.assertEqual({"AC-001"}, authoritative_passed_criteria(plan, core_pass))

    def test_unlinked_task_cannot_close_an_acceptance_criterion(self) -> None:
        command = ["python3", "-m", "unittest", "discover", "-s", "tests"]
        plan = compile_verification_plan(
            criterion_ids=("AC-001",),
            tasks=(replace(_task(command), criterion_ids=()),),
            command_catalog=CommandCatalog(("python3 -m unittest discover -s tests",), (), (), ()),
        )
        self.assertEqual(set(), authoritative_passed_criteria(plan, {"checks": [{"command": command, "status": "PASS"}]}))

    def test_repository_evaluator_entrypoint_is_fingerprinted_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository = Path(temporary)
            script = repository / "scripts" / "run_tests.py"
            script.parent.mkdir()
            script.write_text("print('real tests')\n", encoding="utf-8")
            plan = compile_verification_plan(
                criterion_ids=("AC-001",),
                tasks=(),
                command_catalog=CommandCatalog(("python3 scripts/run_tests.py",), (), (), ()),
                repository=repository,
                baseline_commit="abc123",
            )
            self.assertEqual("abc123", plan["repositoryBaseline"])
            self.assertEqual(
                [{"path": "scripts/run_tests.py", "sha256": plan["evaluatorInputs"][0]["sha256"]}],
                plan["evaluatorInputs"],
            )
            script.write_text("print('mutated evaluator')\n", encoding="utf-8")
            task_plan = compile_verification_plan(
                criterion_ids=("AC-001",),
                tasks=(),
                command_catalog=CommandCatalog(("python3 scripts/run_tests.py",), (), (), ()),
                repository=repository,
                baseline_commit="different",
                baseline_plan=plan,
            )
            self.assertEqual(plan["evaluatorInputs"], task_plan["evaluatorInputs"])
            self.assertEqual("abc123", task_plan["repositoryBaseline"])


if __name__ == "__main__":
    unittest.main()
