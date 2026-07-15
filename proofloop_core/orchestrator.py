from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Iterable, TextIO

from .adapters import ExternalCLIAdapter, HostAdapter, RoleInvocation
from .checks import run_checks
from .diff_guard import inspect_diff
from .events import EventEmitter
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
from .goal import GoalFSM, build_goal_contract
from .memory import prepare_memory, write_memory
from .runtime import ResolvedRuntime


ROLE_SET = {"planner_deep", "explorer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep"}


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
        stream: TextIO | None = None,
        output_format: str = "quiet",
        verbosity: str = "info",
        color: str = "auto",
        goal_mode: bool = False,
        max_goal_cycles: int = 8,
        max_replans: int = 2,
    ):
        self.host = host
        self.repo = Path(repository).resolve()
        self.request = request.strip()
        self.goal_mode = goal_mode
        self.max_goal_cycles = max_goal_cycles
        self.max_replans = max_replans
        self.adapter = adapter or ExternalCLIAdapter(host, routing_policy="goal" if goal_mode else "controller")
        self.strategy_override = strategy_override
        self.timeout_seconds = timeout_seconds
        self.require_observed_routing = require_observed_routing
        self.stream = stream if stream is not None else sys.stdout
        self.output_format = output_format
        self.verbosity = verbosity
        self.color = color
        self.run_dir: Path | None = None
        self.emitter: EventEmitter | None = None
        self.capability: dict[str, Any] = {}
        self.strategy: StrategyDecision | None = None
        self.original_baseline: str | None = None
        self.used_roles: list[str] = []
        self.tasks: list[TaskBrief] = []
        self.goal_fsm: GoalFSM | None = None
        self.active_model: str | None = None
        self.goal_cycles = 0

    def _emit(
        self,
        event_type: str,
        *,
        phase: str,
        message: str,
        level: str = "info",
        task_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if self.emitter is None:
            return None
        return self.emitter.emit(
            event_type,
            phase=phase,
            message=message,
            level=level,
            task_id=task_id,
            data=data,
        )

    def _requested_model_for_role(self, role: str) -> str | None:
        resolver = getattr(self.adapter, "resolve_role", None)
        if callable(resolver):
            return resolver(role).model
        roles = self.capability.get("roles") or {}
        if self.capability.get("mode") != "ROLE_ROUTING_ONLY":
            roles = self.capability.get("externalRoles") or roles
        value = roles.get(role) if isinstance(roles, dict) else None
        model = value.get("model") if isinstance(value, dict) else None
        return model if isinstance(model, str) and model else None

    def _resolved_runtime_for_role(self, role: str) -> ResolvedRuntime | None:
        resolver = getattr(self.adapter, "resolve_role", None)
        return resolver(role) if callable(resolver) else None

    def _goal_transition(self, target: str, reason: str, **data: Any) -> None:
        if self.goal_fsm is None or self.goal_fsm.state == target:
            return
        self.goal_fsm.transition(target, reason=reason, **data)

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
        self.emitter = EventEmitter(
            started["runId"],
            self.run_dir,
            self.stream,
            self.output_format,
            self.verbosity,
            self.color,
        )
        if self.goal_mode:
            self.goal_fsm = GoalFSM(self.run_dir, emit=self._emit)
        self._emit(
            "run.started",
            phase="INIT",
            message="ProofLoop run started.",
            data={"host": self.host, "repository": str(self.repo)},
        )
        try:
            self.transition("INIT")
            write_json(self.run_dir / "request.json", {"schemaVersion": "1.0", "request": self.request})

            self.transition("PREFLIGHT")
            self._emit("context.started", phase="PREFLIGHT", message="Repository preflight started.")
            preflight_result = preflight(self.repo)
            write_json(self.run_dir / "preflight.json", preflight_result)
            if not preflight_result.get("isGitRepository"):
                raise OrchestrationError("GIT_REPOSITORY_REQUIRED", "mutation workflows require a Git repository")
            self.original_baseline = snapshot_worktree(self.repo)
            run_state = read_json(self.run_dir / "run.json")
            run_state["baselineCommit"] = self.original_baseline
            write_json(self.run_dir / "run.json", run_state)
            self._emit(
                "context.ready",
                phase="PREFLIGHT",
                message="Repository preflight completed.",
                data={"repository": str(self.repo), "baseline": self.original_baseline},
            )

            self.transition("CAPABILITY")
            self.capability = self.adapter.probe()
            write_json(self.run_dir / "capability.json", self.capability)
            if not self.capability.get("available", True):
                self._emit(
                    "capability.degraded",
                    phase="CAPABILITY",
                    message=f"{self.host} host capability is unavailable.",
                    level="error",
                    data=self.capability,
                )
                raise OrchestrationError("HOST_CLI_MISSING", f"{self.host} CLI is not available")
            self._emit(
                "capability.detected",
                phase="CAPABILITY",
                message=f"{self.host} host capability detected.",
                data=self.capability,
            )

            self.transition("CLASSIFY")
            self.strategy = classify_request(self.request, self.strategy_override)
            write_json(self.run_dir / "strategy.json", self.strategy.to_dict())
            self._emit(
                "strategy.selected",
                phase="CLASSIFY",
                message=f"Strategy {self.strategy.strategy} selected.",
                data=self.strategy.to_dict(),
            )
            if self.strategy.strategy == "REPOSITORY_ANALYSIS":
                raise OrchestrationError(
                    "ANALYSIS_ORCHESTRATION_NOT_IMPLEMENTED",
                    "v0.4 kernel currently proves mutation workflows; repository analysis remains blocked rather than simulated",
                )

            self.transition("CONTEXT")
            context_path = self.run_dir / "repository-context.json"
            self._emit("context.started", phase="CONTEXT", message="Repository context preparation started.")
            if self.strategy.context_required:
                context = ensure_codegraph(self.repo, context_path, required=True)
                if context.get("verdict") in {"FAIL", "BLOCKED"}:
                    self._emit(
                        "context.failed",
                        phase="CONTEXT",
                        message="Repository context preparation failed.",
                        level="error",
                        data=context,
                    )
                    raise OrchestrationError("REPOSITORY_CONTEXT_BLOCKED", "required repository context is unavailable")
            else:
                context = {"schemaVersion": "1.0", "verdict": "SKIPPED", "reason": "strategy does not require broad context"}
                write_json(context_path, context)
            self._emit(
                "context.ready",
                phase="CONTEXT",
                message="Repository context is ready.",
                data=context,
            )

            if self.strategy.planner_required:
                if self.goal_mode:
                    self._goal_transition("EXPLORE", "repository context is ready")
                    self._run_explorer()
                    self._goal_transition("DESIGN", "exploration evidence is ready")
                self.tasks = self._run_planner()
                if self.strategy.strategy == "HIGH_RISK_ENGINEERING":
                    if self.goal_mode:
                        self._goal_transition("PLAN_REVIEW", "high-risk plan requires independent review")
                    self._run_plan_review()
            else:
                if self.goal_mode:
                    self._goal_transition("IMPLEMENT", "direct goal implementation started")
                self.tasks = self._run_direct_bootstrap()

            if self.goal_mode:
                contract = build_goal_contract(
                    self.request,
                    self.tasks,
                    max_cycles=self.max_goal_cycles,
                    max_replans=self.max_replans,
                )
                write_json(self.run_dir / "goal-contract.json", contract.to_dict())
                for task in self.tasks:
                    memory = prepare_memory(self.repo, task.task_id)
                    self._emit(
                        "memory.prepared",
                        phase="MEMORY",
                        message=f"Memory prepared for {task.task_id}.",
                        task_id=task.task_id,
                        data={
                            "workflowPath": str(memory.workflow_path),
                            "taskPath": str(memory.task_path),
                            "workflowNeedsCompaction": memory.workflow_needs_compaction,
                            "taskNeedsCompaction": memory.task_needs_compaction,
                        },
                    )
                self._goal_transition("IMPLEMENT", "goal contract is ready")

            for task in self.tasks:
                try:
                    self._execute_task(task)
                except Exception as exc:
                    self._emit(
                        "task.failed",
                        phase="EXECUTE",
                        message=f"Task {task.task_id} failed.",
                        level="error",
                        task_id=task.task_id,
                        data={"error": f"{type(exc).__name__}: {exc}"},
                    )
                    raise

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
        phase: str | None = None,
        task_id: str | None = None,
        attempt: int | None = None,
    ) -> dict[str, Any]:
        assert self.run_dir is not None
        if role not in ROLE_SET:
            raise ValueError(role)
        invocation_phase = phase or (
            "PLAN" if role == "planner_deep" else "REVIEW" if role == "reviewer_deep" else "EXECUTE"
        )
        resolved_runtime = self._resolved_runtime_for_role(role)
        requested_model = resolved_runtime.model if resolved_runtime else self._requested_model_for_role(role)
        role_data = {
            "role": role,
            "attempt": attempt,
            "host": self.host,
            "requestedModel": requested_model,
            "routingMode": self.capability.get("mode"),
            "runtime": resolved_runtime.runtime_id if resolved_runtime else self.host,
            "transport": resolved_runtime.transport if resolved_runtime else "adapter",
            "reasoning": resolved_runtime.reasoning if resolved_runtime else None,
            "accessMode": resolved_runtime.access_mode if resolved_runtime else None,
        }
        if resolved_runtime is not None:
            self._emit(
                "runtime.fallback" if resolved_runtime.fallback else "runtime.selected",
                phase=invocation_phase,
                message=(
                    f"Fallback runtime {resolved_runtime.runtime_id} selected for {role}."
                    if resolved_runtime.fallback
                    else f"Runtime {resolved_runtime.runtime_id} selected for {role}."
                ),
                level="warning" if resolved_runtime.fallback else "info",
                task_id=task_id,
                data={**role_data, "reason": resolved_runtime.reason},
            )
        self._emit(
            "model.requested",
            phase=invocation_phase,
            message=f"Model {requested_model or 'unavailable'} requested for {role}.",
            task_id=task_id,
            data={**role_data, "previousModel": self.active_model},
        )
        self._emit(
            "role.queued",
            phase=invocation_phase,
            message=f"{role} queued.",
            task_id=task_id,
            data=role_data,
        )
        self._emit(
            "role.started",
            phase=invocation_phase,
            message=f"{role} started.",
            task_id=task_id,
            data=role_data,
        )
        baseline = snapshot_worktree(self.repo) if immutable_source else None
        invocation = RoleInvocation(
            role=role,
            prompt=prompt,
            repository=self.repo,
            run_dir=self.run_dir,
            task_path=task_path,
            result_path=result_path,
            timeout_seconds=self.timeout_seconds,
            emitter=self.emitter,
            phase=invocation_phase,
            task_id=task_id,
            attempt=attempt,
            runtime=resolved_runtime,
        )
        try:
            result = self.adapter.invoke(invocation)
        except Exception as exc:
            self._emit(
                "role.failed",
                phase=invocation_phase,
                message=f"{role} invocation raised an error.",
                level="error",
                task_id=task_id,
                data={**role_data, "error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        self.used_roles.append(role)
        event = {
            "timestampEpoch": time.time(),
            "sequence": len(self.used_roles),
            "host": self.host,
            "runtime": result.get("runtime") or role_data["runtime"],
            "transport": result.get("transport") or role_data["transport"],
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
        if not result.get("modelEventEmitted"):
            observed = result.get("observedModel")
            evidence_level = result.get("modelEvidence") or (
                "HOST_OUTPUT" if observed else "CLI_REQUESTED_ONLY"
            )
            self._emit(
                "role.model_observed",
                phase=invocation_phase,
                message="Host model observed." if observed else "Requested model could not be observed.",
                level="info" if observed else "warning",
                task_id=task_id,
                data={
                    "role": role,
                    "attempt": attempt,
                    "requestedModel": result.get("requestedModel") or requested_model,
                    "observedModel": observed,
                    "evidenceLevel": evidence_level,
                    "invocationId": result.get("invocationId"),
                },
            )
        observed_model = result.get("observedModel")
        effective_model = observed_model or result.get("requestedModel") or requested_model
        if observed_model and result.get("transport") != "acp":
            self._emit(
                "model.resolved",
                phase=invocation_phase,
                message=f"Runtime resolved model {observed_model}.",
                task_id=task_id,
                data={
                    **role_data,
                    "observedModel": observed_model,
                    "evidenceLevel": result.get("modelEvidence"),
                    "invocationId": result.get("invocationId"),
                },
            )
        if effective_model and effective_model != self.active_model:
            previous_model = self.active_model
            self.active_model = str(effective_model)
            self._emit(
                "model.changed",
                phase=invocation_phase,
                message=f"Active model changed from {previous_model or 'none'} to {effective_model}.",
                task_id=task_id,
                data={
                    **role_data,
                    "previousModel": previous_model,
                    "activeModel": effective_model,
                    "observedModel": observed_model,
                    "evidenceLevel": result.get("modelEvidence") or "UNAVAILABLE",
                    "reason": f"role changed to {role}",
                },
            )
        if immutable_source and baseline is not None:
            changed = changed_source_files(self.repo, baseline)
            if changed:
                self._emit(
                    "role.failed",
                    phase=invocation_phase,
                    message=f"{role} mutated read-only source.",
                    level="error",
                    task_id=task_id,
                    data={**role_data, "changedFiles": changed, "reasonCode": "READ_ONLY_SOURCE_MUTATION"},
                )
                raise OrchestrationError(
                    f"{role.upper()}_MUTATED_SOURCE",
                    f"read-only role changed source files: {changed}",
                    verdict="FAILED",
                )
        if result.get("verdict") not in {"PASS", "PROVEN"}:
            timed_out = bool(result.get("timedOut"))
            cancelled = bool(result.get("cancelled"))
            reason_code = "HOST_TIMEOUT" if timed_out else "HOST_CANCELLED" if cancelled else "HOST_EXIT_NONZERO"
            terminal_type = "role.cancelled" if cancelled else "role.failed"
            self._emit(
                terminal_type,
                phase=invocation_phase,
                message=f"{role} {'cancelled' if cancelled else 'failed'}.",
                level="error",
                task_id=task_id,
                data={
                    **role_data,
                    "exitCode": result.get("exitCode"),
                    "reason": result.get("reason"),
                    "reasonCode": reason_code,
                    "timedOut": timed_out,
                    "cancelled": cancelled,
                    "invocationId": result.get("invocationId"),
                    "invocationDir": result.get("invocationDir"),
                },
            )
            raise OrchestrationError(
                f"{role.upper()}_INVOCATION_FAILED",
                f"{role} invocation failed: {result.get('reason') or result.get('exitCode')}",
            )
        self._emit(
            "role.completed",
            phase=invocation_phase,
            message=f"{role} completed.",
            task_id=task_id,
            data={
                **role_data,
                "requestedModel": result.get("requestedModel") or requested_model,
                "observedModel": result.get("observedModel"),
                "evidenceLevel": result.get("modelEvidence"),
                "exitCode": result.get("exitCode"),
                "invocationId": result.get("invocationId"),
                "invocationDir": result.get("invocationDir"),
            },
        )
        return result

    def _run_explorer(self) -> None:
        assert self.run_dir is not None and self.strategy is not None
        result_path = self.run_dir / "exploration.json"
        prompt = (
            "Act as the read-only ProofLoop explorer.\n"
            f"User request: {self.request}\n"
            f"Strategy: {self.strategy.strategy}\n"
            f"Repository: {self.repo}\n"
            f"Repository context: {self.run_dir / 'repository-context.json'}\n"
            "Map only the relevant entry points, callers, tests, constraints, and open risks. "
            "Do not edit source and do not design speculative features.\n"
            f"Write JSON to {result_path} exactly:\n"
            '{"schemaVersion":"1.0","entryPoints":[],"impactedFiles":[],"tests":[],"constraints":[],"openRisks":[]}\n'
        )
        self._invoke(
            "explorer_fast",
            prompt,
            result_path=result_path,
            immutable_source=True,
            phase="EXPLORE",
        )
        if not result_path.exists():
            raise OrchestrationError("EXPLORATION_ARTIFACT_MISSING", "explorer did not produce exploration.json")

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
Exploration evidence: {self.run_dir / 'exploration.json' if (self.run_dir / 'exploration.json').exists() else 'not requested'}

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
        self._invoke("planner_deep", prompt, result_path=result_path, immutable_source=True, phase="PLAN")
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
        self._invoke(
            "implementer_fast",
            prompt,
            result_path=task_path,
            phase="EXECUTE",
            task_id="TASK-001",
            attempt=1,
        )
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
        self._emit(
            "task.created",
            phase="PLAN",
            message=f"Task {task.task_id} created.",
            task_id=task.task_id,
            data=task_to_dict(task),
        )
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
                self._emit(
                    "task.created",
                    phase="PLAN",
                    message=f"Task {loaded.task_id} created.",
                    task_id=loaded.task_id,
                    data=task_to_dict(loaded),
                )
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
        self._emit("review.started", phase="PLAN", message="High-risk plan review started.")
        self._invoke(
            "reviewer_deep",
            prompt,
            result_path=result_path,
            immutable_source=True,
            phase="PLAN",
        )
        review = _read_optional_json(result_path)
        if not review or review.get("verdict") != "APPROVED":
            raise OrchestrationError("PLAN_REVIEW_NOT_APPROVED", "high-risk plan review did not approve the plan")
        self._emit(
            "review.completed",
            phase="PLAN",
            message="High-risk plan review approved.",
            data={"verdict": review.get("verdict"), "findings": review.get("findings", [])},
        )

    def _execute_task(self, task: TaskBrief) -> None:
        assert self.run_dir is not None
        self._emit(
            "task.started",
            phase="EXECUTE",
            message=f"Task {task.task_id} started.",
            task_id=task.task_id,
            data={"objective": task.objective},
        )
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
            if self.goal_mode:
                self.goal_cycles += 1
                if self.goal_cycles > self.max_goal_cycles:
                    self._goal_transition("EXHAUSTED", "goal cycle budget exhausted", taskId=task.task_id)
                    raise OrchestrationError("GOAL_CYCLE_BUDGET_EXHAUSTED", f"{task.task_id} exceeded goal cycle budget")
                self._goal_transition("IMPLEMENT", "implementation cycle started", taskId=task.task_id)
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
                memory_note = ""
                if self.goal_mode:
                    memory = prepare_memory(self.repo, task.task_id)
                    memory_note = (
                        f"\nRead workflow memory at {memory.workflow_path} and task memory at {memory.task_path}. "
                        "Treat memory as context, not proof."
                    )
                prompt = f"""Execute exactly one ProofLoop task from {task_path}.
Role: {role}
Repository: {self.repo}
Evidence run: {self.run_dir}
{evidence_note}
{memory_note}
Use TDD for behavior changes. Make the smallest change inside allowed paths. Do not weaken tests or expand the contract.
Write optional JSON to {result_path}: {{"status":"DONE|BLOCKED","classification":"LOCAL_IMPLEMENTATION|DESIGN_CONFLICT|SPEC_AMBIGUITY|CONTRACT_CHANGE","summary":"..."}}.
Do not decide whether tests passed; ProofLoop will run them.
"""
                self._invoke(
                    role,
                    prompt,
                    task_path=task_path,
                    result_path=result_path,
                    phase="EXECUTE",
                    task_id=task.task_id,
                    attempt=sequence,
                )
            preinvoked = False

            checks_dir = task_dir / f"attempt-{sequence:02d}-checks"
            if self.goal_mode:
                self._goal_transition("VERIFY", "deterministic verification started", taskId=task.task_id)
            self.transition("VERIFY", taskId=task.task_id, attempt=sequence)
            checks = run_checks(task, self.repo, checks_dir, emitter=self.emitter)
            diff = inspect_diff(task, self.repo, baseline)
            diff_path = task_dir / f"attempt-{sequence:02d}-diff-guard.json"
            write_json(diff_path, diff)
            self._emit(
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
            self._emit(
                "attempt.recorded",
                phase="REPAIR",
                message=f"Attempt {sequence} recorded for {task.task_id}.",
                level="info" if checks.get("verdict") == "PASS" and diff.get("verdict") == "PASS" else "warning",
                task_id=task.task_id,
                data=attempt,
            )
            if self.goal_mode:
                memory = prepare_memory(self.repo, task.task_id)
                write_memory(
                    memory.task_path,
                    (
                        f"## Cycle {sequence}\n\n"
                        f"- Role: {role}\n"
                        f"- Checks: {checks.get('verdict')}\n"
                        f"- Diff guard: {diff.get('verdict')}\n"
                        f"- Failure fingerprint: {attempt.get('failureFingerprint') or 'none'}\n"
                    ),
                    append=True,
                )
            if len(attempts) >= 2 and attempt.get("failureFingerprint") and (
                attempt.get("failureFingerprint") == attempts[-2].get("failureFingerprint")
            ):
                self._emit(
                    "progress.stalled",
                    phase="REPAIR",
                    message="The same failure fingerprint repeated.",
                    level="warning",
                    task_id=task.task_id,
                    data={
                        "fingerprint": attempt.get("failureFingerprint"),
                        "previousAttempt": attempts[-2].get("sequence"),
                        "attempt": sequence,
                        "improved": False,
                    },
                )
            elif len(attempts) >= 2 and checks.get("verdict") == "PASS" and diff.get("verdict") == "PASS":
                self._emit(
                    "progress.detected",
                    phase="REPAIR",
                    message="The latest attempt resolved deterministic failures.",
                    task_id=task.task_id,
                    data={"attempt": sequence, "improved": True},
                )
            decision = decide_next(attempts, task.max_fast_attempts, task.max_recovery_attempts)
            write_json(task_dir / "next-action.json", decision)

            action = decision["action"]
            self.transition(action, taskId=task.task_id, attempt=sequence, reason=decision.get("reason"))
            fast_used = sum(1 for item in attempts if item.get("role") == "implementer_fast")
            recovery_used = sum(1 for item in attempts if item.get("role") == "implementer_recovery")
            self._emit(
                "budget.updated",
                phase="REPAIR",
                message="Repair budget updated.",
                task_id=task.task_id,
                data={
                    "fastRemaining": max(0, task.max_fast_attempts - fast_used),
                    "recoveryRemaining": max(0, task.max_recovery_attempts - recovery_used),
                    "nextAction": action,
                },
            )
            if action == "REVIEW":
                write_json(task_dir / "task-result.json", {"verdict": "PASS", "attempts": sequence})
                self._emit(
                    "task.completed",
                    phase="EXECUTE",
                    message=f"Task {task.task_id} completed.",
                    task_id=task.task_id,
                    data={"attempts": sequence, "verdict": "PASS"},
                )
                return
            if action in {"RETRY_FAST", "RUN_FAST"}:
                if self.goal_mode:
                    self._goal_transition("TRIAGE", "fast implementation requires another cycle", taskId=task.task_id)
                self._emit(
                    "retry.scheduled",
                    phase="REPAIR",
                    message="Fast implementation retry scheduled.",
                    level="warning",
                    task_id=task.task_id,
                    data={
                        "role": "implementer_fast",
                        "attempt": sequence + 1,
                        "reasonCode": "FAST_ATTEMPT_FAILED",
                        "reason": decision.get("reason"),
                        "fingerprint": attempt.get("failureFingerprint"),
                    },
                )
                role = "implementer_fast"
                continue
            if action in {"RUN_RECOVERY", "RETRY_RECOVERY"}:
                if self.goal_mode:
                    self._goal_transition("TRIAGE", "recovery implementation required", taskId=task.task_id)
                self._emit(
                    "recovery.scheduled" if action == "RUN_RECOVERY" else "retry.scheduled",
                    phase="REPAIR",
                    message="Recovery implementation scheduled.",
                    level="warning",
                    task_id=task.task_id,
                    data={
                        "fromRole": role,
                        "toRole": "implementer_recovery",
                        "fromRequestedModel": self._requested_model_for_role(role),
                        "toRequestedModel": self._requested_model_for_role("implementer_recovery"),
                        "attempt": sequence + 1,
                        "reasonCode": "SAME_FINGERPRINT_REPEATED" if action == "RUN_RECOVERY" else "RECOVERY_ATTEMPT_FAILED",
                        "reason": decision.get("reason"),
                        "fingerprint": attempt.get("failureFingerprint"),
                    },
                )
                role = "implementer_recovery"
                continue
            if action == "RETURN_TO_PLANNER":
                replan_limit = self.max_replans if self.goal_mode else 1
                if replan_count >= replan_limit:
                    raise OrchestrationError("REPLAN_BUDGET_EXHAUSTED", f"{task.task_id} still requires redesign")
                self._emit(
                    "replan.scheduled",
                    phase="REPAIR",
                    message="Task replan scheduled.",
                    level="warning",
                    task_id=task.task_id,
                    data={"reasonCode": attempt.get("classification"), "reason": decision.get("reason")},
                )
                if self.goal_mode:
                    self._goal_transition("TRIAGE", "implementation evidence requires redesign", taskId=task.task_id)
                    self._goal_transition("DESIGN", "task returned to planner", taskId=task.task_id)
                task = self._replan_task(task, task_path, attempts[-1])
                replan_count += 1
                role = "implementer_fast"
                continue
            if self.goal_mode:
                self._goal_transition("EXHAUSTED", "task repair budget exhausted", taskId=task.task_id)
            raise OrchestrationError("TASK_REPAIR_BUDGET_EXHAUSTED", f"{task.task_id}: {decision.get('reason')}")

    def _replan_task(self, task: TaskBrief, task_path: Path, attempt: dict[str, Any]) -> TaskBrief:
        assert self.run_dir is not None
        self.transition("REPLAN", taskId=task.task_id)
        result_path = task_path.with_name(task_path.stem + "-replanned.json")
        prompt = f"""Replan the blocked ProofLoop task at {task_path} using exact evidence {attempt['checksRef']} and {attempt['diffGuardRef']}.
Do not edit source. Preserve the user contract unless evidence proves it impossible. Write one valid TaskBrief JSON to {result_path} with the same task id. Do not increase change budgets without explicit evidence and rationale.
"""
        self._invoke(
            "planner_deep",
            prompt,
            task_path=task_path,
            result_path=result_path,
            immutable_source=True,
            phase="REPAIR",
            task_id=task.task_id,
        )
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
            if self.goal_mode:
                self._goal_transition("VERIFY", "final deterministic verification started", reviewCycle=review_cycle)
            checks = run_checks(aggregate, self.repo, self.run_dir / "checks", emitter=self.emitter)
            diff = inspect_diff(aggregate, self.repo, self.original_baseline)
            write_json(self.run_dir / "diff-guard.json", diff)
            self._emit(
                "diff_guard.completed" if diff.get("verdict") == "PASS" else "diff_guard.failed",
                phase="VERIFY",
                message=f"Final diff guard {str(diff.get('verdict')).lower()}.",
                level="info" if diff.get("verdict") == "PASS" else "error",
                data={
                    "verdict": diff.get("verdict"),
                    "metrics": diff.get("metrics", {}),
                    "violations": diff.get("violations", []),
                    "artifact": str(self.run_dir / "diff-guard.json"),
                },
            )
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
                self._emit(
                    "attempt.recorded",
                    phase="REPAIR",
                    message="Final review repair attempt recorded.",
                    task_id="FINAL-REVIEW-REPAIR",
                    data=attempt,
                )
                pending_repair = False
            if checks.get("verdict") != "PASS" or diff.get("verdict") != "PASS":
                if self.goal_mode:
                    self._goal_transition("EXHAUSTED", "final deterministic verification failed", reviewCycle=review_cycle)
                raise OrchestrationError("FINAL_VERIFICATION_FAILED", "final checks or branch diff guard failed", verdict="FAILED")

            self.transition("REVIEW", reviewCycle=review_cycle)
            if self.goal_mode:
                self._goal_transition("DEEP_REVIEW", "deterministic evidence passed", reviewCycle=review_cycle)
            self._emit(
                "review.started",
                phase="REVIEW",
                message=f"Final review cycle {review_cycle} started.",
                data={"reviewCycle": review_cycle},
            )
            cycle_path = self.run_dir / f"review-{review_cycle:02d}.json"
            prompt = f"""Act as the isolated ProofLoop final reviewer.
User request: {self.request}
Plan: {self.run_dir / 'plan.json'}
Task briefs: {self.run_dir / 'tasks'}
Checks: {self.run_dir / 'checks' / 'checks.json'}
Diff guard: {self.run_dir / 'diff-guard.json'}
Goal contract: {self.run_dir / 'goal-contract.json' if self.goal_mode else 'legacy orchestrate mode'}
Review the real source diff from baseline {self.original_baseline}. Do not edit source.
Write JSON to {cycle_path} exactly:
{{
  "verdict": "APPROVED|FIX_REQUIRED|DESIGN_CONFLICT|CANNOT_VERIFY",
  "simplicityVerdict": "MINIMAL|OVERBUILT|CANNOT_VERIFY",
  "criteria": [{{"id":"SC-...","status":"SATISFIED|UNSATISFIED|UNKNOWN","evidence":[]}}],
  "findings": [],
  "deletionCandidates": []
}}
Do not trust implementer summaries. APPROVED requires correct behavior, test integrity, scope compliance, and no unnecessary abstractions.
"""
            self._invoke(
                "reviewer_deep",
                prompt,
                result_path=cycle_path,
                immutable_source=True,
                phase="REVIEW",
            )
            review = _read_optional_json(cycle_path)
            if not review:
                raise OrchestrationError("REVIEW_ARTIFACT_MISSING", "reviewer did not produce a review artifact")
            if self.goal_mode and review.get("verdict") == "APPROVED" and not self._goal_review_satisfied(review):
                review["verdict"] = "FIX_REQUIRED"
                findings = review.get("findings") if isinstance(review.get("findings"), list) else []
                findings.append({"severity": "important", "message": "goal criteria are missing or unsatisfied"})
                review["findings"] = findings
            write_json(self.run_dir / "review.json", review)
            if review.get("verdict") == "APPROVED" and review.get("simplicityVerdict") == "MINIMAL":
                self._emit(
                    "review.completed",
                    phase="REVIEW",
                    message="Final review approved.",
                    data={
                        "reviewCycle": review_cycle,
                        "verdict": review.get("verdict"),
                        "simplicityVerdict": review.get("simplicityVerdict"),
                        "findings": review.get("findings", []),
                    },
                )
                if self.goal_mode:
                    self._goal_transition("CONVERGED", "deep review approved every goal criterion")
                    workflow_memory = prepare_memory(self.repo, "RUN-HANDOFF").workflow_path
                    write_memory(
                        workflow_memory,
                        (
                            f"## Approved run {self.run_dir.name}\n\n"
                            f"- Request: {self.request}\n"
                            f"- Review: {self.run_dir / 'review.json'}\n"
                            f"- Truth evidence: {self.run_dir / 'truth-report.json'}\n"
                        ),
                        append=True,
                    )
                return
            if review_cycle == 1 and (
                review.get("verdict") == "FIX_REQUIRED" or review.get("simplicityVerdict") == "OVERBUILT"
            ):
                if self.goal_mode:
                    self._goal_transition("TRIAGE", "deep review requires repair", reviewCycle=review_cycle)
                self.transition("REVIEW_REPAIR", findings=review.get("findings", []))
                findings = review.get("findings") if isinstance(review.get("findings"), list) else []
                finding = None
                if findings and isinstance(findings[0], dict):
                    finding = findings[0].get("message")
                self._emit(
                    "review.fix_required",
                    phase="REVIEW",
                    message="Final review requires repair.",
                    level="warning",
                    data={
                        "reviewCycle": review_cycle,
                        "verdict": review.get("verdict"),
                        "simplicityVerdict": review.get("simplicityVerdict"),
                        "finding": finding,
                        "findings": findings,
                    },
                )
                if review.get("simplicityVerdict") == "OVERBUILT":
                    self._emit(
                        "review.overbuilt",
                        phase="REVIEW",
                        message="Final review found overbuilt implementation.",
                        level="warning",
                        data={"deletionCandidates": review.get("deletionCandidates", [])},
                    )
                self._emit(
                    "recovery.scheduled",
                    phase="REPAIR",
                    message="Review repair scheduled.",
                    level="warning",
                    data={
                        "fromRole": "reviewer_deep",
                        "toRole": "implementer_recovery",
                        "fromRequestedModel": self._requested_model_for_role("reviewer_deep"),
                        "toRequestedModel": self._requested_model_for_role("implementer_recovery"),
                        "reasonCode": "REVIEW_FIX_REQUIRED",
                        "reason": finding or review.get("simplicityVerdict"),
                    },
                )
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
                    phase="REPAIR",
                    task_id="FINAL-REVIEW-REPAIR",
                    attempt=review_cycle,
                )
                if self.goal_mode:
                    self._goal_transition("IMPLEMENT", "review repair completed", reviewCycle=review_cycle)
                pending_repair = True
                continue
            if review.get("verdict") == "DESIGN_CONFLICT":
                if self.goal_mode and review_cycle == 1:
                    self._goal_transition("DESIGN", "deep review found a design conflict", reviewCycle=review_cycle)
                    self.tasks = self._run_planner()
                    contract = build_goal_contract(
                        self.request,
                        self.tasks,
                        max_cycles=self.max_goal_cycles,
                        max_replans=self.max_replans,
                    )
                    write_json(self.run_dir / "goal-contract.json", contract.to_dict())
                    self._goal_transition("IMPLEMENT", "replanned goal contract is ready")
                    for task in self.tasks:
                        self._execute_task(task)
                    aggregate = aggregate_task(self.tasks)
                    aggregate_path = self.run_dir / "tasks" / "ALL-TASKS.json"
                    write_json(aggregate_path, task_to_dict(aggregate))
                    continue
                if self.goal_mode:
                    self._goal_transition("EXHAUSTED", "design conflict remained after replan")
                raise OrchestrationError("FINAL_REVIEW_DESIGN_CONFLICT", str(review.get("findings") or "design conflict"))
            if self.goal_mode:
                self._goal_transition("EXHAUSTED", "deep review did not approve the goal")
            raise OrchestrationError(
                "REVIEW_NOT_APPROVED",
                str(review.get("findings") or review.get("simplicityVerdict") or review.get("verdict")),
                verdict="FAILED",
            )
        raise OrchestrationError("REVIEW_LOOP_EXHAUSTED", "review remained unapproved after one bounded repair", verdict="FAILED")

    def _goal_review_satisfied(self, review: dict[str, Any]) -> bool:
        assert self.run_dir is not None
        contract = _read_optional_json(self.run_dir / "goal-contract.json") or {}
        expected = {
            item.get("criterion_id")
            for item in contract.get("criteria", [])
            if isinstance(item, dict) and isinstance(item.get("criterion_id"), str)
        }
        observed = {
            item.get("id"): item.get("status")
            for item in review.get("criteria", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        return bool(expected) and all(observed.get(criterion) == "SATISFIED" for criterion in expected)

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

    def _emit_audited_claims(self, assurance: dict[str, Any]) -> None:
        audit = assurance.get("claimAudit") if isinstance(assurance.get("claimAudit"), dict) else {}
        claims = audit.get("claims") if isinstance(audit.get("claims"), list) else []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            status = claim.get("status")
            event_type = (
                "claim.supported"
                if status in {"SUPPORTED", "SUPPORTED_INFERENCE"}
                else "claim.contradicted"
                if status == "CONTRADICTED"
                else "claim.unproven"
            )
            self._emit(
                event_type,
                phase="TRUTH",
                message=str(claim.get("statement") or claim.get("id")),
                level="info" if event_type == "claim.supported" else "error" if event_type == "claim.contradicted" else "warning",
                data=claim,
            )

    def _finalize_truth(self) -> dict[str, Any]:
        assert self.run_dir is not None
        self.transition("TRUTH_GATE")
        trace = self._build_trace_summary()
        self._write_claims(trace)
        assurance = build_assurance_report(self.run_dir)
        write_json(self.run_dir / "assurance-report.json", assurance)
        self._emit_audited_claims(assurance)
        truth = build_truth_report(self.run_dir)
        write_json(self.run_dir / "truth-report.json", truth)
        self.transition(truth["verdict"])
        self._emit(
            "truth.completed",
            phase="TRUTH",
            message=f"Truth gate completed with {truth['verdict']}.",
            level="info" if truth.get("verdict") == "PROVEN" else "warning",
            data={"status": truth.get("verdict"), "verdict": truth.get("verdict"), "truthReport": truth},
        )
        finalize_run(self.repo, truth)
        self._emit(
            "run.completed",
            phase="TRUTH",
            message="ProofLoop run completed.",
            data={"verdict": truth.get("verdict"), "runDir": str(self.run_dir)},
        )
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
        event_type = "run.failed" if verdict == "FAILED" else "run.blocked"
        self._emit(
            event_type,
            phase="TRUTH",
            message=message,
            level="error" if verdict == "FAILED" else "warning",
            data={"verdict": verdict, "code": code, "message": message, "runDir": str(self.run_dir)},
        )
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
    stream: TextIO | None = None,
    output_format: str = "quiet",
    verbosity: str = "info",
    color: str = "auto",
) -> dict[str, Any]:
    return ProofLoopOrchestrator(
        host,
        repository,
        request,
        adapter=adapter,
        strategy_override=strategy_override,
        timeout_seconds=timeout_seconds,
        require_observed_routing=require_observed_routing,
        stream=stream,
        output_format=output_format,
        verbosity=verbosity,
        color=color,
    ).run()


def converge_goal(
    host: str,
    repository: str | Path,
    request: str,
    *,
    adapter: HostAdapter | None = None,
    strategy_override: str | None = None,
    timeout_seconds: int = 1200,
    require_observed_routing: bool = True,
    stream: TextIO | None = None,
    output_format: str = "quiet",
    verbosity: str = "info",
    color: str = "auto",
    max_goal_cycles: int = 8,
    max_replans: int = 2,
) -> dict[str, Any]:
    return ProofLoopOrchestrator(
        host,
        repository,
        request,
        adapter=adapter,
        strategy_override=strategy_override,
        timeout_seconds=timeout_seconds,
        require_observed_routing=require_observed_routing,
        stream=stream,
        output_format=output_format,
        verbosity=verbosity,
        color=color,
        goal_mode=True,
        max_goal_cycles=max_goal_cycles,
        max_replans=max_replans,
    ).run()
