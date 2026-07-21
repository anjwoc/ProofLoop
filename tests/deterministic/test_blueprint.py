from __future__ import annotations

import unittest

from proofloop_core.blueprint import BlueprintValidationError, validate_blueprint
from proofloop_core.task_brief import ChangeBudget, CheckSpec, ProofPlan, SimplicityPlan, TaskBrief


def _task(proof_plan: ProofPlan | None) -> TaskBrief:
    return TaskBrief(
        task_id="TASK-001", objective="bounded", allowed_paths=("src/**",), protected_paths=(),
        required_checks=(CheckSpec(command=["python", "-m", "pytest"]),),
        change_budget=ChangeBudget(1, 10, 0, False),
        simplicity=SimplicityPlan("DIRECT_CHANGE", "bounded", ()),
        criterion_ids=("AC-001",), proof_plan=proof_plan,
    )


class BlueprintValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = {"acceptanceCriteria": [{"id": "AC-001", "statement": "bounded"}]}

    def test_active_blueprint_requires_executable_post_proof(self) -> None:
        with self.assertRaisesRegex(BlueprintValidationError, "proofPlan"):
            validate_blueprint(self.brief, [_task(None)], require_structured_proof=True)

        empty = ProofPlan((), (), (), (), (), ())
        with self.assertRaisesRegex(BlueprintValidationError, "post-implementation"):
            validate_blueprint(self.brief, [_task(empty)], require_structured_proof=True)

        executable = ProofPlan((), (), (CheckSpec(command=["python", "-m", "pytest"]),), (), (), ())
        validate_blueprint(self.brief, [_task(executable)], require_structured_proof=True)


if __name__ == "__main__":
    unittest.main()
