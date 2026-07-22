from typing import Any
from proofloop_core.contracts.task_brief import TaskBrief

class BlueprintValidationError(ValueError):
    pass

def validate_blueprint(
    execution_brief: dict[str, Any],
    tasks: list[TaskBrief],
    *,
    require_structured_proof: bool = False,
) -> None:
    criteria = execution_brief.get("acceptanceCriteria", [])
    
    # 1. Each TaskBrief links ≥1 criterion
    for task in tasks:
        if not task.criterion_ids:
            raise BlueprintValidationError(f"Task {task.task_id} must link at least one criterion")
            
    # 2. Every mandatory obligation maps to a task/check
    linked_criteria: set[str] = set()
    for task in tasks:
        linked_criteria.update(task.criterion_ids)
        
    for ac in criteria:
        cid = ac.get("id")
        if cid and cid not in linked_criteria:
            raise BlueprintValidationError(f"Criterion {cid} is unlinked")
            
    # Also check that all linked criteria actually exist
    existing_cids = {ac.get("id") for ac in criteria if ac.get("id")}
    for cid in linked_criteria:
        if cid not in existing_cids:
            raise BlueprintValidationError(f"Task references unknown criterion {cid}")

    if not require_structured_proof:
        return
    for task in tasks:
        plan = task.proof_plan
        if plan is None:
            raise BlueprintValidationError(f"Task {task.task_id} must declare a proofPlan")
        post_check_count = (
            len(plan.automated_checks)
            + len(plan.adversarial_checks)
            + len(plan.cleanup_checks)
            + len(plan.surface_scenarios)
        )
        if post_check_count == 0:
            raise BlueprintValidationError(
                f"Task {task.task_id} proofPlan needs at least one executable post-implementation check"
            )
