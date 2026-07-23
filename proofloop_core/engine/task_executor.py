"""Task executor: bounded execution and repair for one frozen task contract."""
from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

from proofloop_core.assurance.checks import (
    merge_required_and_post_proof,
    proof_stage_checks,
    run_checks,
    run_post_implementation_proof,
)
from proofloop_core.assurance.diff_guard import inspect_diff
from proofloop_core.context.fingerprint import fingerprint_check_report
from proofloop_core.context.git_snapshot import changed_source_files, snapshot_worktree
from proofloop_core.context.io import append_jsonl, read_json, write_json
from proofloop_core.context.memory import prepare_memory, write_memory
from proofloop_core.contracts.prompt_contract import compile_role_ir
from proofloop_core.engine.exceptions import OrchestrationError
from proofloop_core.engine.repair import RepairAction, RepairState, decide_state

if TYPE_CHECKING:
    from proofloop_core.contracts.task_brief import TaskBrief
    from proofloop_core.engine.orchestrator import ProofLoopOrchestrator


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


class TaskExecutor:
    def __init__(self, orchestrator: "ProofLoopOrchestrator"):
        self.orchestrator = orchestrator

    def _implementation_prompt(
        self,
        task: "TaskBrief",
        *,
        role: str,
        task_path,
        result_path,
        attempts: list[dict[str, Any]],
    ) -> str:
        mandatory_checks = [
            str(item["name"])
            for item in (self.orchestrator.verification_plan or {}).get("mandatoryChecks", [])
            if isinstance(item, dict) and item.get("name")
        ]
        evidence_note = ""
        if attempts:
            last = attempts[-1]
            evidence_note = (
                f"Previous check evidence: {last['checksRef']}; diff evidence: {last['diffGuardRef']}; "
                f"failure fingerprint: {last.get('failureFingerprint') or 'none'}."
            )
        memory_note = ""
        if self.orchestrator.goal_mode:
            memory = prepare_memory(self.orchestrator.repo, task.task_id)
            memory_note = (
                f"Workflow memory: {memory.workflow_path}; task memory: {memory.task_path}. "
                "Memory is context, never proof."
            )
        ir = compile_role_ir(
            self.orchestrator,
            role=role,
            task=task,
            must_do=(
                "Use TDD for behavior changes and make the smallest change inside allowed paths.",
                "Satisfy every Core-owned check; do not replace, skip, or weaken it.",
                "Return only observed implementation status; ProofLoop owns verification.",
            ),
            must_not=(
                "Do not expand the frozen task contract.",
                "Do not create an unpermitted file, dependency, compatibility layer, or abstraction.",
            ),
            context_refs=tuple(
                item
                for item in (
                    f"Repository: {self.orchestrator.repo}",
                    f"Task contract: {task_path}",
                    f"Core-owned checks: {', '.join(mandatory_checks) or 'none declared'}",
                    f"Evidence run: {self.orchestrator.run_dir}",
                    evidence_note,
                    memory_note,
                )
                if item
            ),
            stop_when=task.stop_when,
            escalate_when=task.escalate_on,
            output_contract=(
                f"Write optional JSON to {result_path}: "
                '{"status":"DONE|BLOCKED","classification":"LOCAL_IMPLEMENTATION|DESIGN_CONFLICT|SPEC_AMBIGUITY|CONTRACT_CHANGE|AUTHORIZATION_AMBIGUOUS|REPOSITORY_FACTS_CONFLICT","summary":"..."}.\n'
                "Do not decide whether tests passed; ProofLoop will run them."
            ),
        )
        return self.orchestrator._render_prompt(ir)

    def execute_task(self, task: "TaskBrief") -> None:
        assert (
            self.orchestrator.run_dir is not None
            and self.orchestrator.strategy is not None
            and self.orchestrator.proof_graph is not None
        )
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
                "basis": [task.simplicity.rationale, *task.simplicity.evidence_refs],
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
                    self.orchestrator._goal_transition(
                        "EXHAUSTED", "goal cycle budget exhausted", taskId=task.task_id
                    )
                    raise OrchestrationError(
                        "GOAL_CYCLE_BUDGET_EXHAUSTED",
                        f"{task.task_id} exceeded goal cycle budget",
                    )
                self.orchestrator._goal_transition(
                    "IMPLEMENT", "implementation cycle started", taskId=task.task_id
                )

            sequence = len(attempts) + 1
            self.orchestrator.transition("EXECUTE", taskId=task.task_id, role=role, attempt=sequence)
            result_path = task_dir / f"attempt-{sequence:02d}-{role}-result.json"
            if not preinvoked:
                prompt = self._implementation_prompt(
                    task,
                    role=role,
                    task_path=task_path,
                    result_path=result_path,
                    attempts=attempts,
                )
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
                    raise OrchestrationError(
                        "RECOVERY_BLOCKED_AFTER_DETERMINISTIC_FAILURE",
                        f"{exc}. Recovery could not start after attempt {previous['sequence']} failed deterministic verification.",
                        verdict="BLOCKED",
                    ) from exc
            preinvoked = False

            checks_dir = task_dir / f"attempt-{sequence:02d}-checks"
            if self.orchestrator.goal_mode:
                self.orchestrator._goal_transition(
                    "VERIFY", "deterministic verification started", taskId=task.task_id
                )
            self.orchestrator.transition("VERIFY", taskId=task.task_id, attempt=sequence)
            required_checks = run_checks(
                task,
                self.orchestrator.repo,
                checks_dir,
                emitter=self.orchestrator.emitter,
            )
            post_proof = run_post_implementation_proof(
                task,
                self.orchestrator.repo,
                task_dir / f"attempt-{sequence:02d}-proof",
                emitter=self.orchestrator.emitter,
            )
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
                data={"changedPaths": changed_paths, "attempt": sequence, "diffGuardRef": str(diff_path)},
            )
            self.orchestrator._emit(
                "diff_guard.completed" if diff.get("verdict") == "PASS" else "diff_guard.failed",
                phase="VERIFY",
                message=f"Task {task.task_id} diff guard {str(diff.get('verdict')).lower()}.",
                level="info" if diff.get("verdict") == "PASS" else "error",
                task_id=task.task_id,
                data={
                    "verdict": diff.get("verdict"),
                    "metrics": diff.get("metrics", {}),
                    "violations": diff.get("violations", []),
                    "artifact": str(diff_path),
                },
            )

            role_result = _read_optional_json(result_path) or {}
            attempt_record = {
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
            attempts.append(attempt_record)
            append_jsonl(self.orchestrator.run_dir / "attempts.jsonl", attempt_record)
            write_json(task_dir / "latest-attempt.json", attempt_record)

            if diff.get("verdict") != "PASS":
                violations = [
                    str(item.get("code"))
                    for item in diff.get("violations", [])
                    if isinstance(item, dict) and item.get("code")
                ]
                raise OrchestrationError(
                    "TASK_CONTRACT_VIOLATION",
                    f"{task.task_id} violated the frozen change contract: {', '.join(violations) or 'DIFF_GUARD_FAILED'}.",
                    verdict="FAILED",
                )

            self.orchestrator._emit(
                "attempt.recorded",
                phase="REPAIR",
                message=f"Attempt {sequence} recorded for {task.task_id}.",
                level="info" if checks.get("verdict") == "PASS" else "warning",
                task_id=task.task_id,
                data=attempt_record,
            )
            if self.orchestrator.goal_mode:
                memory = prepare_memory(self.orchestrator.repo, task.task_id)
                write_memory(
                    memory.task_path,
                    f"## Cycle {sequence}\n\n- Role: {role}\n- Checks: {checks.get('verdict')}\n- Diff guard: {diff.get('verdict')}\n- Failure fingerprint: {attempt_record.get('failureFingerprint') or 'none'}\n",
                    append=True,
                )

            state = RepairState.from_attempts(
                attempts,
                max_fast_attempts=task.max_fast_attempts,
                max_recovery_attempts=task.max_recovery_attempts,
            )
            decision = decide_state(state)
            decision_payload = {
                **decision.to_dict(),
                "taskId": task.task_id,
                "attempt": sequence,
                "fastUsed": state.fast_used,
                "fastRemaining": max(0, state.max_fast_attempts - state.fast_used),
                "recoveryUsed": state.recovery_used,
                "recoveryRemaining": max(0, state.max_recovery_attempts - state.recovery_used),
            }
            append_jsonl(self.orchestrator.run_dir / "repair-decisions.jsonl", decision_payload)
            write_json(task_dir / "latest-repair-decision.json", decision_payload)
            self.orchestrator.transition(
                decision.action.value,
                taskId=task.task_id,
                attempt=sequence,
                reason=decision.reason,
                ruleId=decision.rule_id,
            )
            self.orchestrator._emit(
                "budget.updated",
                phase="REPAIR",
                message="Repair budget updated.",
                task_id=task.task_id,
                data=decision_payload,
            )

            match decision.action:
                case RepairAction.REVIEW:
                    write_json(task_dir / "task-result.json", {"verdict": "PASS", "attempts": sequence})
                    self.orchestrator._emit(
                        "task.completed",
                        phase="EXECUTE",
                        message=f"Task {task.task_id} completed.",
                        task_id=task.task_id,
                        data={"attempts": sequence, "verdict": "PASS"},
                    )
                    return
                case RepairAction.RUN_FAST:
                    role = "implementer_fast"
                    self.orchestrator._emit(
                        "retry.scheduled",
                        phase="REPAIR",
                        message="Changed fast implementation retry scheduled.",
                        level="warning",
                        task_id=task.task_id,
                        data={**decision_payload, "role": role, "fingerprint": attempt_record.get("failureFingerprint")},
                    )
                    continue
                case RepairAction.RUN_RECOVERY:
                    self.orchestrator._activate_recovery_protocol()
                    role = "implementer_recovery"
                    self.orchestrator._emit(
                        "recovery.scheduled",
                        phase="REPAIR",
                        message="Recovery implementation scheduled.",
                        level="warning",
                        task_id=task.task_id,
                        data={**decision_payload, "toRole": role, "fingerprint": attempt_record.get("failureFingerprint")},
                    )
                    continue
                case RepairAction.RETURN_TO_PLANNER:
                    if replan_count >= self.orchestrator.max_replans:
                        raise OrchestrationError(
                            "REPLAN_BUDGET_EXHAUSTED",
                            f"{task.task_id} still requires redesign",
                            verdict="BLOCKED",
                        )
                    classification = attempt_record.get("classification")
                    owner_questions = {
                        "SPEC_AMBIGUITY": f"{task.task_id}의 구현 성공 조건 중 무엇을 우선할지 알려주세요.",
                        "AUTHORIZATION_AMBIGUOUS": f"{task.task_id}가 현재 허용 경로 밖을 수정해도 되는지 알려주세요.",
                        "CONTRACT_CHANGE": f"{task.task_id}의 동결된 범위 또는 성공 조건을 바꿔도 되는지 알려주세요.",
                    }
                    if classification in owner_questions:
                        raise OrchestrationError(
                            "TASK_INPUT_REQUIRED",
                            f"{task.task_id} requires an owner decision: {classification}.",
                            verdict="NEEDS_INPUT",
                            questions=(owner_questions[classification],),
                        )
                    self.orchestrator._emit(
                        "replan.scheduled",
                        phase="REPAIR",
                        message="Task replan scheduled.",
                        level="warning",
                        task_id=task.task_id,
                        data=decision_payload,
                    )
                    task = self.orchestrator._replan_task(task, task_path, attempt_record)
                    replan_count += 1
                    role = "implementer_fast"
                    continue
                case RepairAction.BLOCKED:
                    if self.orchestrator.goal_mode:
                        self.orchestrator._goal_transition(
                            "EXHAUSTED", "task repair budget exhausted", taskId=task.task_id
                        )
                    code = (
                        "BLOCKED_IDENTICAL_FAILURE"
                        if decision.rule_id == "R31_IDENTICAL_FAILURE_BLOCK"
                        else "TASK_VERIFICATION_FAILED"
                    )
                    raise OrchestrationError(
                        code,
                        f"{task.task_id} failed deterministic verification: {decision.reason}",
                        verdict="FAILED",
                    )
                case _:
                    raise AssertionError(f"unhandled repair action: {decision.action}")
