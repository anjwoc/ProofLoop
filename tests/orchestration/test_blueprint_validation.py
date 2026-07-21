import unittest

from proofloop_core.blueprint import validate_blueprint, BlueprintValidationError
from proofloop_core.task_brief import TaskBrief, ChangeBudget, SimplicityPlan

class BlueprintValidationTest(unittest.TestCase):
    def test_blueprint_validation_blocks_execution(self):
        execution_brief = {
            "acceptanceCriteria": [
                {"id": "AC-1", "statement": "One"},
                {"id": "AC-2", "statement": "Two"}
            ]
        }
        
        # Valid tasks
        tasks = [
            TaskBrief(
                task_id="T1", objective="One", allowed_paths=(), protected_paths=(),
                required_checks=(),
                change_budget=ChangeBudget(1, 1, 1, False),
                simplicity=SimplicityPlan("STDLIB", "R", ()),
                criterion_ids=("AC-1",)
            ),
            TaskBrief(
                task_id="T2", objective="Two", allowed_paths=(), protected_paths=(),
                required_checks=(),
                change_budget=ChangeBudget(1, 1, 1, False),
                simplicity=SimplicityPlan("STDLIB", "R", ()),
                criterion_ids=("AC-2",)
            )
        ]
        
        # Should pass
        validate_blueprint(execution_brief, tasks)
        
        # Unlinked criterion rejected
        tasks[1] = TaskBrief(
            task_id="T2", objective="Two", allowed_paths=(), protected_paths=(),
            required_checks=(),
            change_budget=ChangeBudget(1, 1, 1, False),
            simplicity=SimplicityPlan("STDLIB", "R", ()),
            criterion_ids=()
        )
        with self.assertRaisesRegex(BlueprintValidationError, "must link at least one criterion"):
            validate_blueprint(execution_brief, tasks)
            
        tasks[1] = TaskBrief(
            task_id="T2", objective="Two", allowed_paths=(), protected_paths=(),
            required_checks=(),
            change_budget=ChangeBudget(1, 1, 1, False),
            simplicity=SimplicityPlan("STDLIB", "R", ()),
            criterion_ids=("AC-3",)
        )
        with self.assertRaisesRegex(BlueprintValidationError, "unlinked"):
            validate_blueprint(execution_brief, tasks)

if __name__ == "__main__":
    unittest.main()
