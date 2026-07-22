from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from proofloop_core.assurance.checks import run_post_implementation_proof, run_proof_stage
from proofloop_core.contracts.task_brief import ChangeBudget, CheckSpec, ProofPlan, SimplicityPlan, SurfaceScenario, TaskBrief


def _task(*, red_command: list[str], automated_command: list[str]) -> TaskBrief:
    return TaskBrief(
        task_id="TASK-001",
        objective="exercise proof plan",
        allowed_paths=("src/**",),
        protected_paths=(),
        required_checks=(CheckSpec(command=[sys.executable, "-c", "raise SystemExit(0)"], name="required"),),
        change_budget=ChangeBudget(1, 10, 0, False),
        simplicity=SimplicityPlan("DIRECT_CHANGE", "bounded test", ()),
        proof_plan=ProofPlan(
            baseline_checks=(CheckSpec(command=[sys.executable, "-c", "raise SystemExit(0)"], name="baseline"),),
            red_checks=(CheckSpec(command=red_command, name="red"),),
            automated_checks=(CheckSpec(command=automated_command, name="automated"),),
            surface_scenarios=(SurfaceScenario(
                scenario_id="surface-1", invocation="invoke local fixture", observable="exit code 0",
                pass_rule="process exits 0", artifact_type="process-log", cleanup=None,
                command=[sys.executable, "-c", "raise SystemExit(0)"],
            ),),
            adversarial_checks=(),
            cleanup_checks=(),
        ),
    )


class ProofPlanExecutionTest(unittest.TestCase):
    def test_baseline_and_red_stages_enforce_opposite_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = _task(
                red_command=[sys.executable, "-c", "raise SystemExit(1)"],
                automated_command=[sys.executable, "-c", "raise SystemExit(0)"],
            )
            baseline = run_proof_stage(task, "baseline", root, root / "baseline")
            red = run_proof_stage(task, "red", root, root / "red")

            self.assertEqual("PASS", baseline["verdict"])
            self.assertTrue(baseline["expectationMet"])
            self.assertEqual("FAIL", red["verdict"])
            self.assertTrue(red["expectationMet"])
            self.assertTrue((root / "red" / "proof-stage.json").is_file())

    def test_post_proof_fails_when_any_executable_stage_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = _task(
                red_command=[sys.executable, "-c", "raise SystemExit(1)"],
                automated_command=[sys.executable, "-c", "raise SystemExit(1)"],
            )
            report = run_post_implementation_proof(task, root, root / "post")

            self.assertEqual("FAIL", report["verdict"])
            self.assertEqual(2, len(report["checks"]))
            self.assertEqual("surface", report["proofStages"][1]["stage"])
            self.assertTrue((root / "post" / "post-proof.json").is_file())


if __name__ == "__main__":
    unittest.main()
