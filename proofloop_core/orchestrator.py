from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from .adapters import ExternalCLIAdapter, HostAdapter, RoleInvocation
from .checks import run_checks
from .diff_guard import inspect_diff
from .fingerprint import fingerprint_check_report
from .git_snapshot import changed_source_files, snapshot_worktree
from .io import read_json, write_json
from .preflight import preflight
from .repair import decide_next
from .repository_context import ensure_codegraph
from .run_state import finalize_run, start_run
from .strategy import StrategyDecision, classify_request
from .task_brief import CheckSpec, ChangeBudget, SimplicityPlan, TaskBrief, load_task_brief
from .trace import summarize_trace
from .truth import build_truth_report
from .assurance import build_assurance_report
from .hosts import role_only_trace_summary


ROLE_SET = {"planner_deep", "implementer_fast", "implementer_recovery", "reviewer_deep"}


class OrchestrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, verdict: str = "BLOCKED"):
        super().__init__(message)
        self.code = code
        self.verdict = verdict


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def _dedupe_checks(tasks: Iterable[TaskBrief]) -> tuple[CheckSpec, ...]:
    seen: set[tuple[Any, ...]] = set()
    checks: list[CheckSpec] = []
    for task in tasks:
        for check in task.required_checks:
            key = (tuple(check.command), check.cwd, check.timeout_seconds, check.name)
            if key not in seen:
                seen.add(key)
                checks.append(check)
    return tuple(checks)


def task_to_dict(task: TaskBrief) -> dict[str, Any]:
    return {
        "id": task.task_id,
        "objective": task.objective,
        "allowedPaths": list(task.allowed_paths),
        "protectedPaths": list(task.protected_paths),
        "requiredChecks": [
            {
                "name": check.name,
                "command": list(check.command),
                "cwd": check.cwd,
                "timeoutSeconds": check.timeout_seconds,
            }
            for check in task.required_checks
        ],
        "changeBudget": {
            "maxChangedFiles": task.change_budget.max_changed_files,
            "maxAddedLines": task.change_budget.max_added_lines,
            "maxNewFiles": task.change_budget.max_new_files,
            "allowDependencyChanges": task.change_budget.allow_dependency_changes,
        },
        "simplicity": {
            "selectedRung": task.simplicity.selected_rung,
            "rationale": task.simplicity.rationale,
            "considered": list(task.simplicity.considered),
        },
        "budgets": {
            "maxFastAttempts": task.max_fast_attempts,
            "maxRecoveryAttempts": task.max_recovery_attempts,
        },
    }


def aggregate_task(tasks: list[TaskBrief]) -> TaskBrief:
    if not tasks:
        raise ValueError("at least one task is required")
    rung_order = {
        "SKIP_NOT_NEEDED": 0,
        "REUSE_EXISTING": 1,
        "STDLIB": 2,
        "PLATFORM_NATIVE": 3,
        "INSTALLED_DEPENDENCY": 4,
        "DIRECT_CHANGE": 5,
        "MINIMAL_NEW_CODE": 6,
    }
    selected = max((task.simplicity.selected_rung for task in tasks), key=lambda item: rung_order[item])
    return TaskBrief(
        task_id="ALL-TASKS",
        objective="; ".join(task.objective for task in tasks),
        allowed_paths=tuple(sorted({path for task in tasks for path in task.allowed_paths})),
        protected_paths=tuple(sorted({path for task in tasks for path in task.protected_paths})),
        required_checks=_dedupe_checks(tasks),
        change_budget=ChangeBudget(
            max_changed_files=sum(task.change_budget.max_changed_files for task in tasks),
            max_added_lines=sum(task.change_budget.max_added_lines for task in tasks),
            max_new_files=sum(task.change_budget.max_new_files for task in tasks),
            allow_dependency_changes=any(task.change_budget.allow_dependency_changes for task in tasks),
        ),
        simplicity=SimplicityPlan(
            selected_rung=selected,
            rationale="Aggregate of approved task simplicity plans.",
            considered=tuple(sorted({item for task in tasks for item in task.simplicity.considered})),
        ),
        max_fast_attempts=max(task.max_fast_attempts for task in tasks),
        max_recovery_attempts=max(task.max_recovery_attempts for task in tasks),
    )


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


class ProofLoopOrchestrator:
    def __init__(
        self,
        host: str,
        repository: str | Path,
        request: str,
        *,
        adapter: HostAdapter | None = None,
        strategy_override: str | None = None,
        timeout_seconds: int = 1200,
        require_observed_routing: bool = True,
    ):
        self.host = host
        self.repo = Path(repository).resolve()
        self.request = request.strip()
        self.adapter = adapter or ExternalCLIAdapter(host)
        self.strategy_override = strategy_override
        self.timeout_seconds = timeout_seconds
        self.require_observed_routing = require_observed_routing
        self.run_dir: Path | None = None
        self.capability: dict[str, Any] = {}
        self.strategy: StrategyDecision | None = None
        self.original_baseline: str | None = None
        self.used_roles: list[str] = []
        self.tasks: list[TaskBrief] = []

    def transition(self, state: str, **details: Any) -> None:
        if self.run_dir is None:
            return
        item = {"timestampEpoch": time.time(), "state": state, **details}
        _append_jsonl(self.run_dir / "transitions.jsonl", item)
        write_json(self.run_dir / "state.json", item)

    def run(self) -> dict[str, Any]:
        if not self.request:
            raise ValueError("request must be non-empty")
        started = start_run(self.repo, self.request)
        self.run_dir = Path(started["runDir"])
        try:
            self.transition("INIT")
            write_json(self.run_dir / "request.json", {"schemaVersion": "1.0", "request": self.request})

            self.transition("PREFLIGHT")
            preflight_result = preflight(self.repo)
            write_json(self.run_dir / "preflight.json", preflight_result)
            if not preflight_result.get("isGitRepository"):
                raise OrchestrationError("GIT_REPOSITORY_REQUIRED", "mutation workflows require a Git repository")
            self.original_baseline = snapshot_worktree(self.repo)
            run_state = read_json(self.run_dir / "run.json")
            run_state["baselineCommit"] = self.original_baseline
            write_json(self.run_dir / "run.json", run_state)

            self.transition("CAPABILITY")
            self.capability = self.adapter.probe()
            write_json(self.run_dir / "capability.json", self.capability)
            if not self.capability.get("available", True):
                raise OrchestrationError("HOST_CLI_MISSING", f"{self.host} CLI is not available")

            self.transition("CLASSIFY")
            self.strategy = classify_request(self.request, self.strategy_override)
            write_json(self.run_dir / "strategy.json", self.strategy.to_dict())
            if self.strategy.strategy == "REPOSITORY_ANALYSIS":
                raise OrchestrationError(
                    "ANALYSIS_ORCHESTRATION_NOT_IMPLEMENTED",
                    "v0.4 kernel currently proves mutation workflows; repository analysis remains blocked rather than simulated",
                )

            self.transition("CONTEXT")
            context_path = self.run_dir / "repository-context.json"
            if self.strategy.context_required:
                context = ensure_codegraph(self.repo, context_path, required=True)
                if context.get("verdict") in {"FAIL", "BLOCKED"}:
                    raise OrchestrationError("REPOSITORY_CONTEXT_BLOCKED", "required repository context is unavailable")
            else:
                write_json(context_path, {"schemaVersion": "1.0", "verdict": "SKIPPED", "reason": "strategy does not require broad context"})

            if self.strategy.planner_required:
                self.tasks = self._run_planner()
                if self.strategy.strategy == "HIGH_RISK_ENGINEERING":
                    self._run_plan_review()
            else:
                self.tasks = self._run_direct_bootstrap()

            for task in self.tasks:
                self._execute_task(task)

            self._final_verification_and_review()
            return self._finalize_truth()
        except OrchestrationError as exc:
            return self._finalize_terminal(exc.verdict, exc.code, str(exc))
        except Exception as exc:
            return self._finalize_terminal("FAILED", "ORCHESTRATOR_INTERNAL_ERROR", f"{type(exc).__name__}: {exc}")

    def _invoke(
        self,
        role: str,
        prompt: str,
        *,
        task_path: Path | None = None,
        result_path: Path | None = None,
        immutable_source: bool = False,
    ) -> dict[str, Any]:
        assert self.run_dir is not None
        if role not in ROLE_SET:
            raise ValueError(role)
        baseline = snapshot_worktree(self.repo) if immutable_source else None
        invocation = RoleInvocation(
            role=role,
            prompt=prompt,
            repository=self.repo,
            run_dir=self.run_dir,
            task_path=task_path,
            result_path=result_path,
            timeout_seconds=self.timeout_seconds,
        )
        result = self.adapter.invoke(invocation)
        self.used_roles.append(role)
        event = {
            "timestampEpoch": time.time(),
            "sequence": len(self.used_roles),
            "host": self.host,
            "role": role,
            "verdict": result.get("verdict"),
            "requestedModel": result.get("requestedModel"),
            "observedModel": result.get("observedModel"),
            "modelEvidence": result.get("modelEvidence"),
            "invocationDir": result.get("invocationDir"),
            "resultPath": str(result_path) if result_path else None,
        }
        _append_jsonl(self.run_dir / "invocations.jsonl", event)
        if not result.get("traceRecorded"):
            trace_event = {
                **event,
                "expectedModel": result.get("requestedModel"),
                "exitCode": result.get("exitCode", 0 if result.get("verdict") == "PASS" else 1),
            }
            _append_jsonl(self.run_dir / "model-trace.jsonl", trace_event)
        if immutable_source and baseline is not None:
            changed = changed_source_files(self.repo, baseline)
            if changed:
                raise OrchestrationError(
                    f"{role.upper()}_MUTATED_SOURCE",
                    f"read-only role changed source files: {changed}",
                    verdict="FAILED",
                )
        if result.get("verdict") not in {"PASS", "PROVEN"}:
            raise OrchestrationError(
                f"{role.upper()}_INVOCATION_FAILED",
                f"{role} invocation failed: {result.get('reason') or result.get('exitCode')}",
            )
        return result

    def _run_planner(self) -> list[TaskBrief]:
        assert self.run_dir is not None and self.strategy is not None
        self.transition("PLAN")
        result_path = self.run_dir / "plan.json"
        prompt = f"""You are the ProofLoop deep planner.

User request:
{self.request}

Strategy: {self.strategy.strategy}
Repository: {self.repo}
Repository evidence: {self.run_dir / 'repository-context.json'}

Do not edit production or test source. Inspect real files and create the smallest sufficient implementation plan.
Write JSON to {result_path} with exactly this shape:
{{
  "schemaVersion": "1.0",
  "verdict": "READY",
  "summary": "concise plan",
  "tasks": [
    {{
      "id": "TASK-001",
      "objective": "...",
      "allowedPaths": ["path/**"],
      "protectedPaths": [],
      "requiredChecks": [{{"name": "tests", "command": ["executable", "arg"], "timeoutSeconds": 300}}],
      "changeBudget": {{"maxChangedFiles": 4, "maxAddedLines": 160, "maxNewFiles": 1, "allowDependencyChanges": false}},
      "simplicity": {{"selectedRung": "REUSE_EXISTING", "rationale": "...", "considered": []}},
      "budgets": {{"maxFastAttempts": 2, "maxRecoveryAttempts": 1}}
    }}
  ]
}}
Rules: 1-4 bounded tasks; every command must be executable in this repository; stop at the first sufficient simplicity rung; no speculative work.
"""
        self._invoke("planner_deep", prompt, result_path=result_path, immutable_source=True)
        return self._materialize_plan(result_path)

    def _run_direct_bootstrap(self) -> list[TaskBrief]:
        """Use one fast role to define and execute a truly bounded direct change."""
        assert self.run_dir is not None
        self.transition("DIRECT_BOOTSTRAP")
        task_path = self.run_dir / "tasks" / "TASK-001.json"
        prompt = f"""You are ProofLoop's fast implementer for a direct verified change.

User request:
{self.request}

Before editing, write a bounded task brief to {task_path} using the standard ProofLoop TaskBrief JSON fields. Then implement that task with the minimum change. Use actual repository test commands. Do not broaden scope or claim success.
"""
        baseline = snapshot_worktree(self.repo)
        self._invoke("implementer_fast", prompt, result_path=task_path)
        if not task_path.exists():
            raise OrchestrationError("DIRECT_TASK_BRIEF_MISSING", "fast implementer did not create a task brief")
        try:
            task = load_task_brief(task_path)
            if not task.allowed_paths:
                raise ValueError("allowedPaths must not be empty")
        except Exception as exc:
            raise OrchestrationError("DIRECT_TASK_BRIEF_INVALID", str(exc), verdict="FAILED") from exc
        # Store baseline so the already-performed direct implementation becomes attempt 1.
        write_json(self.run_dir / "direct-bootstrap.json", {"taskId": task.task_id, "baselineCommit": baseline})
        return [task]

    def _materialize_plan(self, result_path: Path) -> list[TaskBrief]:
        assert self.run_dir is not None
        if not result_path.exists():
            raise OrchestrationError("PLAN_ARTIFACT_MISSING", "planner did not produce plan.json")
        try:
            plan = read_json(result_path)
        except Exception as exc:
            raise OrchestrationError("PLAN_ARTIFACT_INVALID", str(exc), verdict="FAILED") from exc
        if plan.get("verdict") != "READY":
            raise OrchestrationError("PLAN_NOT_READY", str(plan.get("reason") or plan.get("verdict")))
        tasks_raw = plan.get("tasks")
        if not isinstance(tasks_raw, list) or not 1 <= len(tasks_raw) <= 4:
            raise OrchestrationError("PLAN_TASK_COUNT_INVALID", "plan must contain between 1 and 4 tasks", verdict="FAILED")
        tasks_dir = self.run_dir / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        tasks: list[TaskBrief] = []
        ids: set[str] = set()
        for index, raw in enumerate(tasks_raw, start=1):
            if not isinstance(raw, dict):
                raise OrchestrationError("PLAN_TASK_INVALID", f"task {index} is not an object", verdict="FAILED")
            task_id = raw.get("id")
            if not isinstance(task_id, str) or task_id in ids:
                raise OrchestrationError("PLAN_TASK_ID_INVALID", f"invalid or duplicate task id: {task_id}", verdict="FAILED")
            ids.add(task_id)
            path = tasks_dir / f"{task_id}.json"
            write_json(path, raw)
            try:
                loaded = load_task_brief(path)
                if not loaded.allowed_paths:
                    raise ValueError("allowedPaths must not be empty")
                tasks.append(loaded)
            except Exception as exc:
                raise OrchestrationError("PLAN_TASK_SCHEMA_INVALID", f"{task_id}: {exc}", verdict="FAILED") from exc
        (self.run_dir / "plan.md").write_text(str(plan.get("summary") or "ProofLoop plan") + "\n", encoding="utf-8")
        return tasks

    def _run_plan_review(self) -> None:
        assert self.run_dir is not None
        self.transition("PLAN_REVIEW")
        result_path = self.run_dir / "plan-review.json"
        prompt = f"""Review the high-risk ProofLoop plan at {self.run_dir / 'plan.json'} against the user request and repository evidence.
Do not edit source. Write JSON to {result_path}:
{{"verdict":"APPROVED|FIX_REQUIRED|CANNOT_VERIFY","findings":[{{"severity":"critical|important|minor","message":"..."}}]}}
Approve only if acceptance criteria, checks, scope, and escalation conditions are sufficient and minimal.
"""
        self._invoke("reviewer_deep", prompt, result_path=result_path, immutable_source=True)
        review = _read_optional_json(result_path)
        if not review or review.get("verdict") != "APPROVED":
            raise OrchestrationError("PLAN_REVIEW_NOT_APPROVED", "high-risk plan review did not approve the plan")

    def _execute_task(self, task: TaskBrief) -> None:
        assert self.run_dir is not None
        task_path = self.run_dir / "tasks" / f"{task.task_id}.json"
        task_dir = self.run_dir / "task-runs" / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        direct = _read_optional_json(self.run_dir / "direct-bootstrap.json")
        if direct and direct.get("taskId") == task.task_id:
            baseline = str(direct["baselineCommit"])
            role = "implementer_fast"
            preinvoked = True
        else:
            baseline = snapshot_worktree(self.repo)
            role = "implementer_fast"
            preinvoked = False
        write_json(task_dir / "task-state.json", {"taskId": task.task_id, "baselineCommit": baseline})
        attempts: list[dict[str, Any]] = []
        replan_count = 0

        while True:
            sequence = len(attempts) + 1
            self.transition("EXECUTE", taskId=task.task_id, role=role, attempt=sequence)
            result_path = task_dir / f"attempt-{sequence:02d}-{role}-result.json"
            if not preinvoked:
                evidence_note = ""
                if attempts:
                    last = attempts[-1]
                    evidence_note = (
                        f"\nPrevious attempt evidence: {last['checksRef']} and {last['diffGuardRef']}. "
                        f"Failure fingerprint: {last.get('failureFingerprint')}."
                    )
                prompt = f"""Execute exactly one ProofLoop task from {task_path}.
Role: {role}
Repository: {self.repo}
Evidence run: {self.run_dir}
{evidence_note}
Use TDD for behavior changes. Make the smallest change inside allowed paths. Do not weaken tests or expand the contract.
Write optional JSON to {result_path}: {{"status":"DONE|BLOCKED","classification":"LOCAL_IMPLEMENTATION|DESIGN_CONFLICT|SPEC_AMBIGUITY|CONTRACT_CHANGE","summary":"..."}}.
Do not decide whether tests passed; ProofLoop will run them.
"""
                self._invoke(role, prompt, task_path=task_path, result_path=result_path)
            preinvoked = False

            checks_dir = task_dir / f"attempt-{sequence:02d}-checks"
            self.transition("VERIFY", taskId=task.task_id, attempt=sequence)
            checks = run_checks(task, self.repo, checks_dir)
            diff = inspect_diff(task, self.repo, baseline)
            diff_path = task_dir / f"attempt-{sequence:02d}-diff-guard.json"
            write_json(diff_path, diff)
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
                "checksRef": str(checks_dir / "checks.json"),
                "diffGuardRef": str(diff_path),
                "roleResultRef": str(result_path) if result_path.exists() else None,
            }
            attempts.append(attempt)
            _append_jsonl(self.run_dir / "attempts.jsonl", attempt)
            write_json(task_dir / "latest-attempt.json", attempt)
            decision = decide_next(attempts, task.max_fast_attempts, task.max_recovery_attempts)
            write_json(task_dir / "next-action.json", decision)

            action = decision["action"]
            self.transition(action, taskId=task.task_id, attempt=sequence, reason=decision.get("reason"))
            if action == "REVIEW":
                write_json(task_dir / "task-result.json", {"verdict": "PASS", "attempts": sequence})
                return
            if action in {"RETRY_FAST", "RUN_FAST"}:
                role = "implementer_fast"
                continue
            if action in {"RUN_RECOVERY", "RETRY_RECOVERY"}:
                role = "implementer_recovery"
                continue
            if action == "RETURN_TO_PLANNER":
                if replan_count >= 1:
                    raise OrchestrationError("REPLAN_BUDGET_EXHAUSTED", f"{task.task_id} still requires redesign")
                task = self._replan_task(task, task_path, attempts[-1])
                replan_count += 1
                role = "implementer_fast"
                continue
            raise OrchestrationError("TASK_REPAIR_BUDGET_EXHAUSTED", f"{task.task_id}: {decision.get('reason')}")

    def _replan_task(self, task: TaskBrief, task_path: Path, attempt: dict[str, Any]) -> TaskBrief:
        assert self.run_dir is not None
        self.transition("REPLAN", taskId=task.task_id)
        result_path = task_path.with_name(task_path.stem + "-replanned.json")
        prompt = f"""Replan the blocked ProofLoop task at {task_path} using exact evidence {attempt['checksRef']} and {attempt['diffGuardRef']}.
Do not edit source. Preserve the user contract unless evidence proves it impossible. Write one valid TaskBrief JSON to {result_path} with the same task id. Do not increase change budgets without explicit evidence and rationale.
"""
        self._invoke("planner_deep", prompt, task_path=task_path, result_path=result_path, immutable_source=True)
        try:
            revised = load_task_brief(result_path)
        except Exception as exc:
            raise OrchestrationError("REPLAN_TASK_INVALID", str(exc), verdict="FAILED") from exc
        write_json(task_path, read_json(result_path))
        return revised

    def _final_verification_and_review(self) -> None:
        assert self.run_dir is not None and self.original_baseline is not None
        aggregate = aggregate_task(self.tasks)
        aggregate_path = self.run_dir / "tasks" / "ALL-TASKS.json"
        write_json(aggregate_path, task_to_dict(aggregate))
        pending_repair = False

        for review_cycle in range(1, 3):
            self.transition("FINAL_VERIFY", reviewCycle=review_cycle)
            checks = run_checks(aggregate, self.repo, self.run_dir / "checks")
            diff = inspect_diff(aggregate, self.repo, self.original_baseline)
            write_json(self.run_dir / "diff-guard.json", diff)
            if pending_repair:
                attempt = {
                    "sequence": self._attempt_count() + 1,
                    "taskId": "FINAL-REVIEW-REPAIR",
                    "timestampEpoch": time.time(),
                    "role": "implementer_recovery",
                    "checkVerdict": checks.get("verdict"),
                    "diffVerdict": diff.get("verdict"),
                    "failureFingerprint": _combined_fingerprint(checks, diff),
                    "classification": "REVIEW_FINDINGS",
                    "checksRef": str(self.run_dir / "checks" / "checks.json"),
                    "diffGuardRef": str(self.run_dir / "diff-guard.json"),
                }
                _append_jsonl(self.run_dir / "attempts.jsonl", attempt)
                pending_repair = False
            if checks.get("verdict") != "PASS" or diff.get("verdict") != "PASS":
                raise OrchestrationError("FINAL_VERIFICATION_FAILED", "final checks or branch diff guard failed", verdict="FAILED")

            self.transition("REVIEW", reviewCycle=review_cycle)
            cycle_path = self.run_dir / f"review-{review_cycle:02d}.json"
            prompt = f"""Act as the isolated ProofLoop final reviewer.
User request: {self.request}
Plan: {self.run_dir / 'plan.json'}
Task briefs: {self.run_dir / 'tasks'}
Checks: {self.run_dir / 'checks' / 'checks.json'}
Diff guard: {self.run_dir / 'diff-guard.json'}
Review the real source diff from baseline {self.original_baseline}. Do not edit source.
Write JSON to {cycle_path} exactly:
{{
  "verdict": "APPROVED|FIX_REQUIRED|DESIGN_CONFLICT|CANNOT_VERIFY",
  "simplicityVerdict": "MINIMAL|OVERBUILT|CANNOT_VERIFY",
  "findings": [],
  "deletionCandidates": []
}}
Do not trust implementer summaries. APPROVED requires correct behavior, test integrity, scope compliance, and no unnecessary abstractions.
"""
            self._invoke("reviewer_deep", prompt, result_path=cycle_path, immutable_source=True)
            review = _read_optional_json(cycle_path)
            if not review:
                raise OrchestrationError("REVIEW_ARTIFACT_MISSING", "reviewer did not produce a review artifact")
            write_json(self.run_dir / "review.json", review)
            if review.get("verdict") == "APPROVED" and review.get("simplicityVerdict") == "MINIMAL":
                return
            if review_cycle == 1 and (
                review.get("verdict") == "FIX_REQUIRED" or review.get("simplicityVerdict") == "OVERBUILT"
            ):
                self.transition("REVIEW_REPAIR", findings=review.get("findings", []))
                repair_result = self.run_dir / "review-repair-result.json"
                repair_prompt = f"""Repair the final ProofLoop review findings in {cycle_path}.
Use the aggregate task contract at {aggregate_path}. Preserve scope and change budgets. If the review says OVERBUILT, remove unnecessary abstractions without weakening correctness, security, or tests. Do not decide pass/fail; ProofLoop will rerun all checks.
Write optional JSON to {repair_result}: {{"status":"DONE|BLOCKED","classification":"REVIEW_FINDINGS","summary":"..."}}.
"""
                self._invoke(
                    "implementer_recovery",
                    repair_prompt,
                    task_path=aggregate_path,
                    result_path=repair_result,
                )
                pending_repair = True
                continue
            if review.get("verdict") == "DESIGN_CONFLICT":
                raise OrchestrationError("FINAL_REVIEW_DESIGN_CONFLICT", str(review.get("findings") or "design conflict"))
            raise OrchestrationError(
                "REVIEW_NOT_APPROVED",
                str(review.get("findings") or review.get("simplicityVerdict") or review.get("verdict")),
                verdict="FAILED",
            )
        raise OrchestrationError("REVIEW_LOOP_EXHAUSTED", "review remained unapproved after one bounded repair", verdict="FAILED")

    def _attempt_count(self) -> int:
        assert self.run_dir is not None
        path = self.run_dir / "attempts.jsonl"
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def _build_trace_summary(self) -> dict[str, Any]:
        assert self.run_dir is not None
        mode = self.capability.get("mode")
        if mode == "ROLE_ROUTING_ONLY":
            result = role_only_trace_summary(self.host)
            result["requiredRoles"] = list(dict.fromkeys(self.used_roles))
            result["eventCount"] = len(self.used_roles)
        else:
            required = list(dict.fromkeys(self.used_roles))
            result = summarize_trace(self.run_dir / "model-trace.jsonl", required_roles=required)
            result["host"] = self.host
            result["capabilityMode"] = mode
        write_json(self.run_dir / "model-trace-summary.json", result)
        return result

    def _write_claims(self, trace: dict[str, Any]) -> None:
        assert self.run_dir is not None
        claims: list[dict[str, Any]] = [
            {
                "id": "checks-pass",
                "category": "CHECK_RESULT",
                "kind": "FACT",
                "statement": "All required commands passed.",
                "evidence": [{"artifact": "checks/checks.json", "jsonPointer": "/verdict", "equals": "PASS"}],
            },
            {
                "id": "scope-pass",
                "category": "CHANGE_SCOPE",
                "kind": "FACT",
                "statement": "The final diff passed scope and integrity checks.",
                "evidence": [{"artifact": "diff-guard.json", "jsonPointer": "/verdict", "equals": "PASS"}],
            },
            {
                "id": "review-approved",
                "category": "REVIEW_RESULT",
                "kind": "FACT",
                "statement": "The independent review approved the change.",
                "evidence": [{"artifact": "review.json", "jsonPointer": "/verdict", "equals": "APPROVED"}],
            },
            {
                "id": "simplicity-minimal",
                "category": "SIMPLICITY",
                "kind": "FACT",
                "statement": "The reviewer found the implementation minimal.",
                "evidence": [{"artifact": "review.json", "jsonPointer": "/simplicityVerdict", "equals": "MINIMAL"}],
            },
        ]
        if trace.get("routingClaimed"):
            if trace.get("routingObserved"):
                claims.append(
                    {
                        "id": "model-routing-observed",
                        "category": "MODEL_ROUTING",
                        "kind": "FACT",
                        "statement": "Role-specific model routing was observed in host evidence.",
                        "evidence": [{"artifact": "model-trace-summary.json", "jsonPointer": "/routingObserved", "equals": True}],
                    }
                )
            else:
                claims.append(
                    {
                        "id": "model-routing-unproven",
                        "category": "MODEL_ROUTING",
                        "kind": "UNKNOWN",
                        "statement": "The requested role-specific model routing could not be proven from host evidence.",
                        "evidence": [],
                    }
                )
        write_json(self.run_dir / "claims.json", {"schemaVersion": "1.0", "claims": claims})

    def _finalize_truth(self) -> dict[str, Any]:
        assert self.run_dir is not None
        self.transition("TRUTH_GATE")
        trace = self._build_trace_summary()
        self._write_claims(trace)
        assurance = build_assurance_report(self.run_dir)
        write_json(self.run_dir / "assurance-report.json", assurance)
        truth = build_truth_report(self.run_dir)
        write_json(self.run_dir / "truth-report.json", truth)
        self.transition(truth["verdict"])
        finalize_run(self.repo, truth)
        return {"verdict": truth["verdict"], "runDir": str(self.run_dir), "truthReport": truth}

    def _finalize_terminal(self, verdict: str, code: str, message: str) -> dict[str, Any]:
        if self.run_dir is None:
            return {"verdict": verdict, "code": code, "message": message}
        report = {
            "schemaVersion": "2.0",
            "verdict": verdict,
            "blockers": [code],
            "unproven": [],
            "message": message,
            "evidence": {},
        }
        write_json(self.run_dir / "truth-report.json", report)
        self.transition(verdict, code=code, message=message)
        finalize_run(self.repo, report)
        return {"verdict": verdict, "code": code, "message": message, "runDir": str(self.run_dir), "truthReport": report}


def orchestrate(
    host: str,
    repository: str | Path,
    request: str,
    *,
    adapter: HostAdapter | None = None,
    strategy_override: str | None = None,
    timeout_seconds: int = 1200,
    require_observed_routing: bool = True,
) -> dict[str, Any]:
    return ProofLoopOrchestrator(
        host,
        repository,
        request,
        adapter=adapter,
        strategy_override=strategy_override,
        timeout_seconds=timeout_seconds,
        require_observed_routing=require_observed_routing,
    ).run()
