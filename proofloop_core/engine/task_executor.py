"""Task executor: handles the execution and repair loop of a single task."""
from __future__ import annotations

import time
import hashlib
import json
from typing import TYPE_CHECKING, Any

from proofloop_core.assurance.checks import (
    merge_required_and_post_proof,
    proof_stage_checks,
    run_checks,
    run_post_implementation_proof,
)
from proofloop_core.context.io import read_json, write_json, append_jsonl
from proofloop_core.context.fingerprint import fingerprint_check_report
from proofloop_core.prompting.prompt_ir import PromptIR, PromptMetadata
from proofloop_core.engine.exceptions import OrchestrationError
from proofloop_core.assurance.diff_guard import inspect_diff
from proofloop_core.context.git_snapshot import changed_source_files, snapshot_worktree
from proofloop_core.engine.repair import decide_next
from proofloop_core.context.memory import prepare_memory, write_memory


def _read_optional_json(path):
    try:
        return read_json(path)
    except FileNotFoundError:
        return None


def _combined_fingerprint(checks: dict[str, Any], diff: dict[str, Any]) -> str | None:
    check_fp = fingerprint_check_report(checks)
    violations = diff.get("violations") or []
    if not check_fp and not violations:
        return None
    payload = {
        "checkFingerprint": check_fp,
        "violations": [
            {"code": item.get("code"), "path": item.get("path"), "detail": item.get("detail")}
            for item in violations
            if isinstance(item, dict)
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:24]

if TYPE_CHECKING:
    from proofloop_core.engine.orchestrator import ProofLoopOrchestrator
    from proofloop_core.contracts.blueprint import TaskBrief


class TaskExecutor:
    def __init__(self, orchestrator: "ProofLoopOrchestrator"):
        self.orchestrator = orchestrator

    def execute_task(self, task: TaskBrief) -> None:
        assert self.orchestrator.run_dir is not None and self.orchestrator.strategy is not None and self.orchestrator.proof_graph is not None
        self.orchestrator._emit(
            "task.started",
            phase="EXECUTE",
            message=f"Task {task.task_id} started.",
            task_id=task.task_id,
            data={"objective": task.objective},
        )
        self.orchestrator._emit(
            "implementation.started",
            phase="IMPLEMENT",
            message=f"Implementing {task.objective}",
            task_id=task.task_id,
            data={
                "basis": [task.simplicity.rationale],
                "targets": list(task.allowed_paths),
                "path": task.allowed_paths[0] if len(task.allowed_paths) == 1 else None,
            },
        )
        task_path = self.orchestrator.run_dir / "tasks" / f"{task.task_id}.json"
        task_dir = self.orchestrator.run_dir / "task-runs" / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        direct = _read_optional_json(self.orchestrator.run_dir / "direct-bootstrap.json")
        if direct and direct.get("taskId") == task.task_id:
            baseline = str(direct["baselineCommit"])
            role = "implementer_fast"
            preinvoked = True
        else:
            baseline = snapshot_worktree(self.orchestrator.repo)
            role = "implementer_fast"
            preinvoked = False
        write_json(task_dir / "task-state.json", {"taskId": task.task_id, "baselineCommit": baseline})
        attempts: list[dict[str, Any]] = []
        replan_count = 0

        if preinvoked and any(proof_stage_checks(task, stage) for stage in ("baseline", "red")):
            raise OrchestrationError(
                "PREIMPLEMENTATION_PROOF_UNAVAILABLE",
                f"{task.task_id} declares baseline/red proof after direct bootstrap mutation",
                verdict="BLOCKED",
            )
        if not preinvoked:
            self.orchestrator._run_preimplementation_proof(task, task_dir)

        while True:
            if self.orchestrator.goal_mode:
                self.orchestrator.goal_cycles += 1
                if self.orchestrator.goal_cycles > self.orchestrator.max_goal_cycles:
                    self.orchestrator._goal_transition("EXHAUSTED", "goal cycle budget exhausted", taskId=task.task_id)
                    raise OrchestrationError("GOAL_CYCLE_BUDGET_EXHAUSTED", f"{task.task_id} exceeded goal cycle budget")
                self.orchestrator._goal_transition("IMPLEMENT", "implementation cycle started", taskId=task.task_id)
            sequence = len(attempts) + 1
            self.orchestrator.transition("EXECUTE", taskId=task.task_id, role=role, attempt=sequence)
            result_path = task_dir / f"attempt-{sequence:02d}-{role}-result.json"
            if not preinvoked:
                evidence_note = ""
                if attempts:
                    last = attempts[-1]
                    evidence_note = f"\nPrevious attempt evidence: {last['checksRef']} and {last['diffGuardRef']}. Failure fingerprint: {last.get('failureFingerprint')}."
                memory_note = ""
                if self.orchestrator.goal_mode:
                    memory = prepare_memory(self.orchestrator.repo, task.task_id)
                    memory_note = f"\nRead workflow memory at {memory.workflow_path} and task memory at {memory.task_path}. Treat memory as context, not proof."
                mandatory_checks = []
                for item in (self.orchestrator.verification_plan or {}).get("mandatoryChecks", []):
                    if not isinstance(item, dict) or not item.get("name"):
                        continue
                    mandatory_checks.append(str(item["name"]))
                contract_note = (
                    f"Task objective: {task.objective}\n"
                    f"Allowed paths: {', '.join(task.allowed_paths)}\n"
                    f"Core-owned checks after implementation: {', '.join(mandatory_checks) or 'none declared'}"
                )
                ir = PromptIR(
                    prompt_id=f"execute-{sequence}",
                    request_id="todo",
                    contract_id="todo",
                    blueprint_id="todo",
                    role="implementer_fast",
                    goal=self.orchestrator.refined_request or task.objective,
                    stop_when="",
                    deliverables=(),
                    evidence_requirements=(),
                    allowed_scope=(),
                    protected_scope=(),
                    must_do=(
                        "Use TDD for behavior changes. Make the smallest change inside allowed paths.",
                        "Satisfy every Core-owned check listed in the task context; do not replace or weaken it.",
                    ),
                    must_not=("Do not weaken tests or expand the contract.",),
                    context_refs=(
                        f"Repository: {self.orchestrator.repo}\n"
                        f"Task contract: {task_path}\n{contract_note}\n"
                        f"Refined request contract:\n{self.orchestrator.refined_request or task.objective}\n"
                        f"Evidence run: {self.orchestrator.run_dir}\n{evidence_note}\n{memory_note}".strip(),
                    ),
                    allowed_tools=(),
                    output_contract=(f"Write optional JSON to {result_path}: {{\"status\":\"DONE|BLOCKED\",\"classification\":\"LOCAL_IMPLEMENTATION|DESIGN_CONFLICT|SPEC_AMBIGUITY|CONTRACT_CHANGE\",\"summary\":\"...\"}}.\nDo not decide whether tests passed; ProofLoop will run them.\n"),
                    escalate_when=(),
                    metadata=PromptMetadata(compiler_version=str(task_path), generation_time=role)
                )

                prompt = self.orchestrator._render_prompt(ir)
                try:
                    self.orchestrator._invoke(
                        role,
                        prompt,
                        task_path=task_path,
                        result_path=result_path,
                        phase="EXECUTE",
                        task_id=task.task_id,
                        attempt=sequence,
                    )
                except OrchestrationError as exc:
                    if exc.verdict != "BLOCKED" or not attempts:
                        raise
                    previous = attempts[-1]
                    if previous.get("checkVerdict") == "PASS" and previous.get("diffVerdict") == "PASS":
                        raise
                    diff = _read_optional_json(previous["diffGuardRef"]) or {}
                    violations = diff.get("violations") or []
                    detail = ", ".join(
                        str(item.get("code"))
                        for item in violations
                        if isinstance(item, dict) and item.get("code")
                    ) or f"checks={previous.get('checkVerdict')}, diff={previous.get('diffVerdict')}"
                    raise OrchestrationError(
                        "RECOVERY_BLOCKED_AFTER_DETERMINISTIC_FAILURE",
                        f"{exc}. Recovery could not start after attempt {previous['sequence']} failed deterministic verification: {detail}.",
                        verdict="BLOCKED",
                    ) from exc
            
            preinvoked = False
            checks_dir = task_dir / f"attempt-{sequence:02d}-checks"
            if self.orchestrator.goal_mode:
                self.orchestrator._goal_transition("VERIFY", "deterministic verification started", taskId=task.task_id)
            self.orchestrator.transition("VERIFY", taskId=task.task_id, attempt=sequence)
            
            required_checks = run_checks(task, self.orchestrator.repo, checks_dir, emitter=self.orchestrator.emitter)
            post_proof = run_post_implementation_proof(task, self.orchestrator.repo, task_dir / f"attempt-{sequence:02d}-proof", emitter=self.orchestrator.emitter)
            checks = merge_required_and_post_proof(task.task_id, required_checks, post_proof)
            
            combined_checks_path = task_dir / f"attempt-{sequence:02d}-verification.json"
            write_json(combined_checks_path, checks)
            diff = inspect_diff(task, self.orchestrator.repo, baseline)
            diff_path = task_dir / f"attempt-{sequence:02d}-diff-guard.json"
            write_json(diff_path, diff)
            changed_paths = changed_source_files(self.orchestrator.repo, baseline)
            self.orchestrator._emit(
                "implementation.changed",
                phase="IMPLEMENT",
                message=f"Observed {len(changed_paths)} changed file(s).",
                task_id=task.task_id,
                data={
                    "changedPaths": changed_paths,
                    "attempt": sequence,
                    "diffGuardRef": str(diff_path),
                },
            )
            
            self.orchestrator._emit(
                "diff_guard.completed" if diff.get("verdict") == "PASS" else "diff_guard.failed",
                phase="VERIFY",
                message=f"Task {task.task_id} diff guard {str(diff.get('verdict')).lower()}.",
                level="info" if diff.get("verdict") == "PASS" else "error",
                task_id=task.task_id,
                data={"verdict": diff.get("verdict"), "metrics": diff.get("metrics", {}), "violations": diff.get("violations", []), "artifact": str(diff_path)},
            )
            
            role_result = _read_optional_json(result_path) or {}
            attempt = {
                "sequence": sequence,
                "taskId": task.task_id,
                "timestampEpoch": time.time(),
                "role": role,
                "checkVerdict": checks.get("verdict"),
                "diffVerdict": diff.get("verdict"),
                "failureFingerprint": _combined_fingerprint(checks, diff),
                "classification": role_result.get("classification"),
                "checksRef": str(combined_checks_path),
                "requiredChecksRef": str(checks_dir / "checks.json"),
                "postProofRef": str(task_dir / f"attempt-{sequence:02d}-proof" / "post-proof.json"),
                "diffGuardRef": str(diff_path),
                "roleResultRef": str(result_path) if result_path.exists() else None,
            }
            attempts.append(attempt)
            append_jsonl(self.orchestrator.run_dir / "attempts.jsonl", attempt)
            write_json(task_dir / "latest-attempt.json", attempt)

            if diff.get("verdict") != "PASS":
                violations = [
                    str(item.get("code"))
                    for item in diff.get("violations", [])
                    if isinstance(item, dict) and item.get("code")
                ]
                raise OrchestrationError(
                    "TASK_CONTRACT_VIOLATION",
                    f"{task.task_id} violated the frozen change contract: {', '.join(violations) or 'DIFF_GUARD_FAILED'}. No automatic model retry was started.",
                    verdict="FAILED",
                )
            
            self.orchestrator._emit(
                "attempt.recorded",
                phase="REPAIR",
                message=f"Attempt {sequence} recorded for {task.task_id}.",
                level="info" if checks.get("verdict") == "PASS" and diff.get("verdict") == "PASS" else "warning",
                task_id=task.task_id,
                data=attempt,
            )
            
            if self.orchestrator.goal_mode:
                memory = prepare_memory(self.orchestrator.repo, task.task_id)
                write_memory(memory.task_path, f"## Cycle {sequence}\n\n- Role: {role}\n- Checks: {checks.get('verdict')}\n- Diff guard: {diff.get('verdict')}\n- Failure fingerprint: {attempt.get('failureFingerprint') or 'none'}\n", append=True)
            
            if len(attempts) >= 2 and attempt.get("failureFingerprint") and (attempt.get("failureFingerprint") == attempts[-2].get("failureFingerprint")):
                self.orchestrator._emit(
                    "progress.stalled",
                    phase="REPAIR",
                    message="The same failure fingerprint repeated.",
                    level="warning",
                    task_id=task.task_id,
                    data={"fingerprint": attempt.get("failureFingerprint"), "previousAttempt": attempts[-2].get("sequence"), "attempt": sequence, "improved": False},
                )
            elif len(attempts) >= 2 and checks.get("verdict") == "PASS" and diff.get("verdict") == "PASS":
                self.orchestrator._emit(
                    "progress.detected",
                    phase="REPAIR",
                    message="The latest attempt resolved deterministic failures.",
                    task_id=task.task_id,
                    data={"attempt": sequence, "improved": True},
                )
            
            decision = decide_next(attempts, task.max_fast_attempts, task.max_recovery_attempts)
            write_json(task_dir / "next-action.json", decision)

            action = decision["action"]
            self.orchestrator.transition(action, taskId=task.task_id, attempt=sequence, reason=decision.get("reason"))
            fast_used = sum(1 for item in attempts if item.get("role") == "implementer_fast")
            recovery_used = sum(1 for item in attempts if item.get("role") == "implementer_recovery")
            self.orchestrator._emit(
                "budget.updated",
                phase="REPAIR",
                message="Repair budget updated.",
                task_id=task.task_id,
                data={"fastRemaining": max(0, task.max_fast_attempts - fast_used), "recoveryRemaining": max(0, task.max_recovery_attempts - recovery_used), "nextAction": action},
            )
            
            if action == "REVIEW":
                write_json(task_dir / "task-result.json", {"verdict": "PASS", "attempts": sequence})
                self.orchestrator._emit("task.completed", phase="EXECUTE", message=f"Task {task.task_id} completed.", task_id=task.task_id, data={"attempts": sequence, "verdict": "PASS"})
                return
            if action in {"RETRY_FAST", "RUN_FAST"}:
                if self.orchestrator.goal_mode:
                    self.orchestrator._goal_transition("TRIAGE", "fast implementation requires another cycle", taskId=task.task_id)
                self.orchestrator._emit(
                    "retry.scheduled", phase="REPAIR", message="Fast implementation retry scheduled.", level="warning", task_id=task.task_id,
                    data={"role": "implementer_fast", "attempt": sequence + 1, "reasonCode": "FAST_ATTEMPT_FAILED", "reason": decision.get("reason"), "fingerprint": attempt.get("failureFingerprint")}
                )
                role = "implementer_fast"
                continue
            if action in {"RUN_RECOVERY", "RETRY_RECOVERY"}:
                if action == "RUN_RECOVERY":
                    self.orchestrator._activate_recovery_protocol()
                if self.orchestrator.goal_mode:
                    self.orchestrator._goal_transition("TRIAGE", "recovery implementation required", taskId=task.task_id)
                self.orchestrator._emit(
                    "recovery.scheduled" if action == "RUN_RECOVERY" else "retry.scheduled", phase="REPAIR", message="Recovery implementation scheduled.", level="warning", task_id=task.task_id,
                    data={"fromRole": role, "toRole": "implementer_recovery", "fromRequestedModel": self.orchestrator._requested_model_for_role(role), "toRequestedModel": self.orchestrator._requested_model_for_role("implementer_recovery"), "attempt": sequence + 1, "reasonCode": "SAME_FINGERPRINT_REPEATED" if action == "RUN_RECOVERY" else "RECOVERY_ATTEMPT_FAILED", "reason": decision.get("reason"), "fingerprint": attempt.get("failureFingerprint")}
                )
                role = "implementer_recovery"
                continue
            if action == "RETURN_TO_PLANNER":
                if self.orchestrator.max_replans != 1:
                    replan_limit = self.orchestrator.max_replans
                else:
                    replan_limit = 3 if self.orchestrator.strategy.tier == "T3" else 2

                if replan_count >= replan_limit:
                    raise OrchestrationError("REPLAN_BUDGET_EXHAUSTED", f"{task.task_id} still requires redesign")

                classification = attempt.get("classification")
                if classification in {"SPEC_AMBIGUITY", "AUTHORIZATION_AMBIGUOUS", "CONTRACT_CHANGE"}:
                    question = {
                        "SPEC_AMBIGUITY": f"{task.task_id}의 구현 성공 조건 중 무엇을 우선할지 알려주세요.",
                        "AUTHORIZATION_AMBIGUOUS": f"{task.task_id}가 현재 허용 경로 밖을 수정해도 되는지 알려주세요.",
                        "CONTRACT_CHANGE": f"{task.task_id}의 동결된 범위 또는 성공 조건을 바꿔도 되는지 알려주세요.",
                    }[classification]
                    raise OrchestrationError(
                        "TASK_INPUT_REQUIRED",
                        f"{task.task_id} requires an owner decision: {classification}.",
                        verdict="NEEDS_INPUT",
                        questions=(question,),
                    )
                if classification == "CONTRACT_CHANGE":
                    for obligation in self.orchestrator.proof_graph.obligations:
                        obligation.revision += 1
                        obligation.status = "OPEN"

                self.orchestrator._emit("replan.scheduled", phase="REPAIR", message="Task replan scheduled.", level="warning", task_id=task.task_id, data={"reasonCode": classification, "reason": decision.get("reason")})
                if self.orchestrator.goal_mode:
                    self.orchestrator._goal_transition("TRIAGE", "implementation evidence requires redesign", taskId=task.task_id)
                    self.orchestrator._goal_transition("DESIGN", "task returned to planner", taskId=task.task_id)
                task = self.orchestrator._replan_task(task, task_path, attempts[-1])
                replan_count += 1
                role = "implementer_fast"
                continue
            if self.orchestrator.goal_mode:
                self.orchestrator._goal_transition("EXHAUSTED", "task repair budget exhausted", taskId=task.task_id)
            raise OrchestrationError(
                "TASK_VERIFICATION_FAILED",
                f"{task.task_id} failed deterministic verification: {decision.get('reason')}. No automatic model retry was started.",
                verdict="FAILED",
            )
