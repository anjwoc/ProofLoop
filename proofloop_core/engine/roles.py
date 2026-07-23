from __future__ import annotations
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from proofloop_core.context.io import write_json, read_json
from proofloop_core.prompting.prompt_ir import PromptIR, PromptMetadata
from proofloop_core.contracts.task_brief import TaskBrief, load_task_brief
from proofloop_core.engine.exceptions import OrchestrationError


if TYPE_CHECKING:
    from proofloop_core.engine.orchestrator import ProofLoopOrchestrator

def run_explorer(orchestrator: "ProofLoopOrchestrator") -> Any:
    assert orchestrator.run_dir is not None and orchestrator.strategy is not None
    result_path = orchestrator.run_dir / "exploration.json"
    ir = PromptIR(
        prompt_id="explorer-1",
        request_id="todo",
        contract_id="todo",
        blueprint_id="todo",
        role="explorer_fast",
        goal=orchestrator.refined_request or str(orchestrator.request),
        stop_when="",
        deliverables=(),
        evidence_requirements=(),
        allowed_scope=(),
        protected_scope=(),
        must_do=("Map only the relevant entry points, callers, tests, constraints, and open risks.",),
        must_not=("Do not edit source and do not design speculative features.",),
        context_refs=(
            f"Strategy: {orchestrator.strategy.strategy}",
            f"Repository: {orchestrator.repo}",
            f"Repository context: {orchestrator.run_dir / 'repository-context.json'}"
        ),
        allowed_tools=(),
        output_contract=f"Write JSON to {result_path} exactly:\n{{\"schemaVersion\":\"1.0\",\"entryPoints\":[],\"impactedFiles\":[],\"tests\":[],\"constraints\":[],\"openRisks\":[]}}\n",
        escalate_when=(),
        metadata=PromptMetadata(compiler_version="todo", generation_time="todo")
    )
    prompt = orchestrator._render_prompt(ir)
    orchestrator._invoke(
        "explorer_fast",
        prompt,
        result_path=result_path,
        immutable_source=True,
        phase="EXPLORE",
    )
    if not result_path.exists():
        raise OrchestrationError("EXPLORATION_ARTIFACT_MISSING", "explorer did not produce exploration.json")

def run_planner(orchestrator: "ProofLoopOrchestrator") -> Any:
    assert orchestrator.run_dir is not None and orchestrator.strategy is not None and orchestrator.intent is not None
    orchestrator.transition("PLAN")
    result_path = orchestrator.run_dir / "plan.json"
    accepted_criteria = ", ".join(item.criterion_id for item in orchestrator.intent.acceptance_criteria)
    ir = PromptIR(
        prompt_id="planner-1",
        request_id="todo",
        contract_id="todo",
        blueprint_id="todo",
        role="planner_deep",
        goal=orchestrator.refined_request or str(orchestrator.request),
        stop_when="",
        deliverables=(),
        evidence_requirements=(),
        allowed_scope=(),
        protected_scope=(),
        must_do=("Inspect real files and create the smallest sufficient implementation plan.",),
        must_not=("Do not edit production or test source.",),
        context_refs=(
            f"Strategy: {orchestrator.strategy.strategy}",
            f"Repository: {orchestrator.repo}",
            f"Repository evidence: {orchestrator.run_dir / 'repository-context.json'}",
            f"Exploration evidence: {orchestrator.run_dir / 'exploration.json' if (orchestrator.run_dir / 'exploration.json').exists() else 'not requested'}"
        ),
        allowed_tools=(),
        output_contract=(
            f"Write JSON to {result_path} with exactly this shape:\n"
            "{\n"
            '  "schemaVersion": "1.0",\n'
            '  "verdict": "READY",\n'
            '  "summary": "concise plan",\n'
            '  "tasks": [\n'
            '    {\n'
            '      "id": "TASK-001",\n'
            '      "objective": "...",\n'
            f'      "criterion_ids": ["{orchestrator.intent.acceptance_criteria[0].criterion_id}"],\n'
            '      "allowedPaths": ["path/**"],\n'
            '      "protectedPaths": [],\n'
            '      "requiredChecks": [{"name": "tests", "command": ["executable", "arg"]}],\n'
            '      "proofPlan": {"baselineChecks": [], "redChecks": [], "automatedChecks": [{"name": "behavior", "command": ["executable", "arg"]}], "surfaceScenarios": [], "adversarialChecks": [], "cleanupChecks": []},\n'
            '      "changeBudget": {"maxChangedFiles": <positive integer derived from allowedPaths>, "maxAddedLines": <optional positive integer only when a line cap is justified>, "maxNewFiles": <nonnegative integer derived from deliverables>, "allowDependencyChanges": false},\n'
            '      "simplicity": {"selectedRung": "REUSE_EXISTING", "rationale": "...", "considered": []},\n'
            '      "budgets": {"maxFastAttempts": 1, "maxRecoveryAttempts": 0}\n'
            '    }\n'
            '  ]\n'
            "}\n"
            f"Rules: 1-4 bounded tasks; every task must link one or more declared criterion_ids ({accepted_criteria}); replace every <...> budget placeholder with an integer derived from the declared deliverables before writing JSON; every command (including every surface scenario command) must be executable in this repository; proofPlan automated/adversarial/cleanup/surface checks run after the change and must contain at least one executable check; baseline checks must pass before mutation and red checks must fail before mutation; stop at the first sufficient simplicity rung; no speculative work.\n"
        ),
        escalate_when=(),
        metadata=PromptMetadata(compiler_version="todo", generation_time="todo")
    )
    prompt = orchestrator._render_prompt(ir)
    orchestrator._invoke("planner_deep", prompt, result_path=result_path, immutable_source=True, phase="PLAN")
    return materialize_plan(orchestrator, result_path)

def run_plan_review(orchestrator: "ProofLoopOrchestrator") -> Any:
    assert orchestrator.run_dir is not None
    orchestrator.transition("PLAN_REVIEW")
    result_path = orchestrator.run_dir / "plan-review.json"
    ir = PromptIR(
        prompt_id="plan-review-1",
        request_id="todo",
        contract_id="todo",
        role="reviewer_deep", blueprint_id="PLAN_REVIEW",
        goal="",
        stop_when="",
        deliverables=(),
        evidence_requirements=(),
        allowed_scope=(),
        protected_scope=(),
        must_do=(),
        must_not=("Do not edit source.",),
        context_refs=(),
        allowed_tools=(),
        output_contract=(
            f"Write JSON to {result_path}:\n"
            '{"verdict":"APPROVED|FIX_REQUIRED|CANNOT_VERIFY","findings":[{"severity":"critical|important|minor","message":"..."}]}\n'
            "Approve only if acceptance criteria, checks, scope, and escalation conditions are sufficient and minimal.\n"
        ),
        escalate_when=(),
        metadata=PromptMetadata(compiler_version=str(orchestrator.run_dir / 'plan.json'), generation_time="todo")
    )
    prompt = orchestrator._render_prompt(ir)
    orchestrator._emit("review.started", phase="PLAN", message="High-risk plan review started.")
    orchestrator._invoke(
        "reviewer_deep",
        prompt,
        result_path=result_path,
        immutable_source=True,
        phase="PLAN",
    )
    review = read_json(result_path) if result_path.exists() else None
    if not review or review.get("verdict") != "APPROVED":
        raise OrchestrationError("PLAN_REVIEW_NOT_APPROVED", "high-risk plan review did not approve the plan")
    orchestrator._emit(
        "review.completed",
        phase="PLAN",
        message="High-risk plan review approved.",
        data={"verdict": review.get("verdict"), "findings": review.get("findings", [])},
    )

def materialize_plan(orchestrator: "ProofLoopOrchestrator", result_path) -> Any:
    assert orchestrator.run_dir is not None and orchestrator.intent is not None
    if not result_path.exists():
        raise OrchestrationError("PLAN_ARTIFACT_MISSING", "planner did not produce plan.json")
    try:
        plan = read_json(result_path)
    except Exception as exc:
        raise OrchestrationError(
            "PLAN_ARTIFACT_INVALID",
            str(exc),
            verdict="FAILED",
            failure_domain="PROOFLOOP",
        ) from exc
    if plan.get("verdict") != "READY":
        raise OrchestrationError("PLAN_NOT_READY", str(plan.get("reason") or plan.get("verdict")))
    tasks_raw = plan.get("tasks")
    if not isinstance(tasks_raw, list) or not 1 <= len(tasks_raw) <= 4:
        raise OrchestrationError(
            "PLAN_TASK_COUNT_INVALID",
            "plan must contain between 1 and 4 tasks",
            verdict="FAILED",
            failure_domain="PROOFLOOP",
        )
    tasks_dir = orchestrator.run_dir / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[TaskBrief] = []
    ids: set[str] = set()
    for index, raw in enumerate(tasks_raw, start=1):
        if not isinstance(raw, dict):
            raise OrchestrationError(
                "PLAN_TASK_INVALID",
                f"task {index} is not an object",
                verdict="FAILED",
                failure_domain="PROOFLOOP",
            )
        task_id = raw.get("id")
        if not isinstance(task_id, str) or task_id in ids:
            raise OrchestrationError(
                "PLAN_TASK_ID_INVALID",
                f"invalid or duplicate task id: {task_id}",
                verdict="FAILED",
                failure_domain="PROOFLOOP",
            )
        ids.add(task_id)
        path = tasks_dir / f"{task_id}.json"
        write_json(path, raw)
        try:
            loaded = load_task_brief(path)
            if not loaded.allowed_paths:
                raise ValueError("allowedPaths must not be empty")
            tasks.append(loaded)
            orchestrator._emit(
                "contract.frozen",
                phase="CONTRACT",
                message=f"{loaded.task_id} contract validated and frozen.",
                task_id=loaded.task_id,
                data={
                    "deliverables": list(loaded.deliverables or loaded.allowed_paths),
                    "successCriteria": [
                        item.statement
                        for item in orchestrator.intent.acceptance_criteria
                        if item.criterion_id in loaded.criterion_ids
                    ],
                    "allowedPaths": list(loaded.allowed_paths),
                    "artifact": str(path),
                },
            )
            orchestrator._emit(
                "task.created",
                phase="PLAN",
                message=f"Task {loaded.task_id} created.",
                task_id=loaded.task_id,
                data=raw,
            )
        except Exception as exc:
            raise OrchestrationError(
                "PLAN_TASK_SCHEMA_INVALID",
                f"{task_id}: {exc}",
                verdict="FAILED",
                failure_domain="PROOFLOOP",
            ) from exc
    if (
        len(tasks) == 1
        and not tasks[0].criterion_ids
        and len(orchestrator.intent.acceptance_criteria) == 1
    ):
        criterion_id = orchestrator.intent.acceptance_criteria[0].criterion_id
        task = replace(tasks[0], criterion_ids=(criterion_id,))
        tasks[0] = task
        path = tasks_dir / f"{task.task_id}.json"
        raw_task = read_json(path)
        raw_task["criterion_ids"] = [criterion_id]
        write_json(path, raw_task)
        orchestrator._emit(
            "criterion_mapping.inferred",
            phase="PLAN",
            message=f"Single-task plan deterministically linked {task.task_id} to {criterion_id}.",
            task_id=task.task_id,
            data={"taskId": task.task_id, "criterionIds": [criterion_id], "reason": "SINGLE_TASK_SINGLE_CRITERION"},
        )
    (orchestrator.run_dir / "plan.md").write_text(str(plan.get("summary") or "ProofLoop plan") + "\n", encoding="utf-8")
    return tasks
