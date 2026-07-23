from __future__ import annotations

import hashlib
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, TextIO

from proofloop_core.analysis.usage import budgeted_token_total
from proofloop_core.assurance.checks import (
    merge_check_reports,
    merge_required_and_post_proof,
    run_checks,
    run_post_implementation_proof,
    run_proof_stage,
)
from proofloop_core.assurance.diff_guard import inspect_diff
from proofloop_core.assurance.live_evidence import seal_core_evidence
from proofloop_core.context.proof_graph import Evidence, ProofObligation
from proofloop_core.context.trace import summarize_trace
from proofloop_core.contracts.task_brief import load_task_brief
from proofloop_core.contracts.verification_plan import authoritative_passed_criteria, with_mandatory_checks
from proofloop_core.prompting.prompt_ir import PromptMetadata
from proofloop_core.runtimes.hosts import role_only_trace_summary

from proofloop_core.runtimes.adapters import ExternalCLIAdapter, HostAdapter, RoleInvocation
from proofloop_core.context.events import EventBus, EventEmitter
from proofloop_core.context.git_snapshot import changed_source_files, snapshot_worktree
from proofloop_core.context.io import read_json, write_json, append_jsonl
from proofloop_core.assurance.preflight import preflight
from proofloop_core.context.repository_context import ensure_codegraph
from proofloop_core.contracts.run_state import finalize_run, start_run
from proofloop_core.contracts.expected_output import write_run_outcome
from proofloop_core.engine.strategy import StrategyDecision, classify_request
from proofloop_core.contracts.task_brief import CheckSpec, ChangeBudget, SimplicityPlan, TaskBrief
from proofloop_core.assurance.truth import build_truth_report
from proofloop_core.assurance.assurance import build_assurance_report
from proofloop_core.contracts.goal import build_goal_contract
from proofloop_core.context.memory import prepare_memory
from proofloop_core.runtimes.runtime import ResolvedRuntime
from proofloop_core.prompting.prompt_ir import PromptIR
from proofloop_core.prompting.renderers import render_prompt
from proofloop_core.analysis.usage import build_usage_summary
from proofloop_core.analysis.tokscale import TokScaleAdapter
from proofloop_core.engine.intent import format_intent_contract
from proofloop_core.engine.intent import IntentContract, compile_intent
from proofloop_core.engine.intent_gate import evaluate_intent
from proofloop_core.context.grounding import collect_grounding
from proofloop_core.assurance.live_evidence import validate_core_evidence
from proofloop_core.contracts.execution_brief import compose_execution_brief
from proofloop_core.context.proof_graph import ProofGraph
from proofloop_core.contracts.request_envelope import create as create_request_envelope
from proofloop_core.engine.skill_registry import SkillContract
from proofloop_core.analysis.workload import probe_repository_signals
from proofloop_core.engine.domain_runtime import build_repository_fingerprint
from proofloop_core.engine.exceptions import OrchestrationError
from proofloop_core.engine.roles import run_direct_bootstrap, run_explorer, run_plan_review, run_planner
from proofloop_core.engine.skills import resolve_skills
from proofloop_core.engine.task_executor import TaskExecutor
from proofloop_core.contracts.verification_plan import (
    compile_verification_plan,
)


ROLE_SET = {"planner_deep", "explorer_fast", "implementer_fast", "implementer_recovery", "reviewer_deep"}


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def _live_evidence_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Persist integrity status without duplicating check output into events."""
    return {
        "schemaVersion": "1.0",
        "status": result.get("status"),
        "reasons": result.get("reasons", []),
        "candidateDigest": result.get("candidateDigest"),
        "verificationPlanSha256": result.get("verificationPlanSha256"),
    }


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
        criterion_ids=tuple(sorted({item for task in tasks for item in task.criterion_ids})),
        deliverables=tuple(sorted({item for task in tasks for item in task.deliverables})),
        dependencies=tuple(sorted({item for task in tasks for item in task.dependencies})),
        interfaces=tuple(sorted({item for task in tasks for item in task.interfaces})),
        context_refs=tuple(sorted({item for task in tasks for item in task.context_refs})),
        tool_allowlist=tuple(sorted({item for task in tasks for item in task.tool_allowlist})),
        stop_when="All aggregated task contracts are satisfied.",
        escalate_on=tuple(sorted({item for task in tasks for item in task.escalate_on})),
    )


def task_to_dict(task: TaskBrief) -> dict[str, Any]:
    def check_to_dict(check: CheckSpec) -> dict[str, Any]:
        return {
            "name": check.name,
            "command": list(check.command),
            "cwd": check.cwd,
            "timeoutSeconds": check.timeout_seconds,
        }

    proof_plan = None
    if task.proof_plan is not None:
        proof_plan = {
            "baselineChecks": [check_to_dict(check) for check in task.proof_plan.baseline_checks],
            "redChecks": [check_to_dict(check) for check in task.proof_plan.red_checks],
            "automatedChecks": [check_to_dict(check) for check in task.proof_plan.automated_checks],
            "surfaceScenarios": [
                {
                    "scenario_id": scenario.scenario_id,
                    "invocation": scenario.invocation,
                    "observable": scenario.observable,
                    "pass_rule": scenario.pass_rule,
                    "artifact_type": scenario.artifact_type,
                    "cleanup": scenario.cleanup,
                    "command": list(scenario.command),
                    "cwd": scenario.cwd,
                    "timeoutSeconds": scenario.timeout_seconds,
                }
                for scenario in task.proof_plan.surface_scenarios
            ],
            "adversarialChecks": [check_to_dict(check) for check in task.proof_plan.adversarial_checks],
            "cleanupChecks": [check_to_dict(check) for check in task.proof_plan.cleanup_checks],
        }
    return {
        "id": task.task_id,
        "title": task.title,
        "objective": task.objective,
        "criterion_ids": list(task.criterion_ids),
        "deliverables": list(task.deliverables),
        "dependencies": list(task.dependencies),
        "interfaces": list(task.interfaces),
        "allowedPaths": list(task.allowed_paths),
        "protectedPaths": list(task.protected_paths),
        "context_refs": list(task.context_refs),
        "tool_allowlist": list(task.tool_allowlist),
        "requiredChecks": [check_to_dict(check) for check in task.required_checks],
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
        **({"proofPlan": proof_plan} if proof_plan is not None else {}),
        "stop_when": task.stop_when,
        "escalate_on": list(task.escalate_on),
    }


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
        mode: str = "orchestrate",
        skills_enabled: bool = True,
        experimental_domain_packs: bool = False,
        event_bus: EventBus | None = None,
    ):
        if mode not in {"orchestrate", "adaptive", "goal", "audit"}:
            raise ValueError(f"unsupported ProofLoop mode: {mode}")
        self.host = host
        self.repo = Path(repository).resolve()
        # Preserve the exact request bytes for the immutable envelope; the
        # stripped form remains the input to the legacy pipeline for now.
        self.raw_request = request
        self.request = request.strip()
        self.mode = mode
        self.skills_enabled = skills_enabled
        self.experimental_domain_packs = experimental_domain_packs
        self.goal_mode = goal_mode or mode == "goal"
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
        self.event_bus = event_bus
        self.run_dir: Path | None = None
        self.emitter: EventEmitter | None = None
        self.capability: dict[str, Any] = {}
        self.strategy: StrategyDecision | None = None
        self.original_baseline: str | None = None
        self.used_roles: list[str] = []
        self.tasks: list[TaskBrief] = []
        self.goal_state = "INIT"
        self.active_model: str | None = None
        self.goal_cycles = 0
        self.intent: IntentContract | None = None
        self.intent_gate_result: Any | None = None
        self.execution_brief: dict[str, Any] | None = None
        self.proof_graph: ProofGraph | None = None
        self.verification_plan: dict[str, Any] | None = None
        self.selected_skills: list[SkillContract] = []
        self.selected_skill_references: dict[str, list[dict[str, Any]]] = {}
        self.repository_fingerprint: dict[str, Any] | None = None
        self.token_budget: int | None = None
        self.consumed_tokens = 0
        self.diff_reclassified = False

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

    def _render_prompt(self, ir: PromptIR) -> str:
        """Render against the runtime selected for this role, not a generic host label."""
        resolved = self._resolved_runtime_for_role(ir.role)
        provider = resolved.runtime_id if resolved is not None else self.host
        return render_prompt(ir, provider)

    def _record_prompt_projection(
        self,
        *,
        invocation_id: str,
        role: str,
        resolved_runtime: ResolvedRuntime | None,
        prompt: str,
    ) -> None:
        assert self.run_dir is not None
        provider = resolved_runtime.runtime_id if resolved_runtime is not None else self.host
        model = resolved_runtime.model if resolved_runtime is not None else "unknown"
        write_json(
            self.run_dir / "prompt-projections" / f"{invocation_id}.json",
            {
                "schemaVersion": "1.0",
                "invocationId": invocation_id,
                "role": role,
                "controllerHost": self.host,
                "runtime": provider,
                "model": model,
                "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "promptText": prompt,
            },
        )
        (self.run_dir / "prompt-projections" / f"{invocation_id}.md").write_text(prompt, encoding="utf-8")
        reason = getattr(resolved_runtime, "reasoning", None) if resolved_runtime is not None else None
        self._emit(
            "role_prompt.rendered",
            phase="PLAN" if role == "planner_deep" else "PROOF",
            message=f"Rendered prompt for {role}",
            data={
                "invocationId": invocation_id,
                "role": role,
                "model": model,
                "runtime": provider,
                "promptText": prompt,
                "reason": reason or f"dispatched to {role}",
            },
        )

    def _goal_transition(self, target: str, reason: str, **data: Any) -> None:
        if not self.goal_mode or self.goal_state == target:
            return
        previous = self.goal_state
        self.goal_state = target
        item = {"previous": previous, "state": target, "reason": reason, **data}
        append_jsonl(self.run_dir / "goal-transitions.jsonl", item)
        write_json(self.run_dir / "goal-state.json", item)
        self._emit(
            "goal.state_changed",
            phase=target,
            message=f"Goal state changed: {previous} -> {target}.",
            data=item,
        )

    def transition(self, state: str, **details: Any) -> None:
        if self.run_dir is None:
            return
        item = {"timestampEpoch": time.time(), "state": state, **details}
        append_jsonl(self.run_dir / "transitions.jsonl", item)
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
            bus=self.event_bus,
        )
        self._emit(
            "run.started",
            phase="INIT",
            message="ProofLoop run started.",
            data={"host": self.host, "repository": str(self.repo)},
        )
        try:
            self.transition("INIT")
            write_json(self.run_dir / "request.json", {"schemaVersion": "1.0", "request": self.request})
            envelope = create_request_envelope(
                request_id=started["runId"],
                raw_text=self.raw_request,
                repo_root=str(self.repo),
                host_requested=self.host,
                invocation_source=self.host,
            )
            write_json(self.run_dir / "request-envelope.json", envelope.to_dict())
            self._emit(
                "request.envelope_created",
                phase="INIT",
                message="Immutable request envelope created.",
                data={
                    "requestId": envelope.request_id,
                    "rawHash": envelope.raw_hash,
                    "artifact": str(self.run_dir / "request-envelope.json"),
                },
            )
            intent_gate_result = evaluate_intent(self.request, adapter=self.adapter, run_dir=self.run_dir, repo=self.repo)
            self.intent_gate_result = intent_gate_result
            write_json(self.run_dir / "intent-gate.json", intent_gate_result.to_dict())
            if intent_gate_result.clarity.value == "owner_decision_required":
                raise OrchestrationError("INTENT_OWNER_DECISION_REQUIRED", intent_gate_result.owner_question or "owner decision", verdict="BLOCKED")
            if intent_gate_result.clarity.value == "blocked":
                raise OrchestrationError("INTENT_GATE_BLOCKED", intent_gate_result.blocked_reason or "blocked", verdict="BLOCKED")

            # The intent contract is downstream of the immutable envelope, so
            # its originalRequest must retain the exact request bytes too.
            # Individual derived fields are normalized by compile_intent.
            self.intent = compile_intent(self.raw_request, intent_gate_result=self.intent_gate_result)
            write_json(self.run_dir / "intent-contract.json", self.intent.to_dict())
            self.refined_request = format_intent_contract(self.intent)
            write_json(self.run_dir / "refined-request-shadow.json", {"refinedRequest": self.refined_request})
            self._emit(
                "intent.compiled",
                phase="INIT",
                message="Original request compiled into a scope-preserving intent contract.",
                data={
                    "originalRequestHash": self.intent.original_request_hash,
                    "acceptanceCriteria": len(self.intent.acceptance_criteria),
                    "unknowns": list(self.intent.unknowns),
                    "artifact": str(self.run_dir / "intent-contract.json"),
                },
            )

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
            repository_signals = probe_repository_signals(
                self.repo,
                self.intent.target_artifacts if self.intent is not None else (),
            )
            self.strategy = classify_request(
                self.request,
                self.strategy_override,
                repository_signals=repository_signals,
                intent_gate_result=self.intent_gate_result,
            )
            if self.strategy.strategy == "PLANNED_IMPLEMENTATION" and self.mode in {"orchestrate", "goal"}:
                self.strategy = replace(
                    self.strategy,
                    planner_required=True,
                    reviewer_required=True,
                    explorer_required=self.mode == "goal" or self.strategy.explorer_required,
                )
            if (
                intent_gate_result.authority.value == "read_only"
                and self.strategy.strategy != "REPOSITORY_ANALYSIS"
                and self.mode != "audit"
            ):
                raise OrchestrationError(
                    "INTENT_AUTHORITY_MISMATCH",
                    "a read-only request cannot enter a repository-mutation strategy",
                    verdict="BLOCKED",
                )
            write_json(self.run_dir / "strategy.json", self.strategy.to_dict())
            self.repository_fingerprint = build_repository_fingerprint(
                self.repo,
                self.request,
                self.intent.target_artifacts if self.intent is not None else (),
            )
            write_json(self.run_dir / "repository-fingerprint.json", self.repository_fingerprint)
            self._emit(
                "strategy.selected",
                phase="CLASSIFY",
                message=f"Strategy {self.strategy.strategy} selected.",
                data=self.strategy.to_dict(),
            )
            self._initialize_proof_graph()
            resolve_skills(self)


            self.transition("CONTEXT")

            # Phase 4 Grounding Snapshot (Shadow)
            self._emit("grounding.started", phase="CONTEXT", message="Grounding snapshot collection started.")
            grounding_snapshot = collect_grounding(
                request_id=self.emitter.run_id,
                repo_root=self.repo,
                tier=self.strategy.tier,
                request_text=self.request,
            )
            self.grounding_snapshot = grounding_snapshot
            write_json(self.run_dir / "grounding-snapshot.json", grounding_snapshot.to_dict())
            for signal in grounding_snapshot.injection_signals:
                self._emit(
                    "grounding.injection_detected",
                    phase="CONTEXT",
                    message=f"Untrusted instruction pattern detected in {signal.path}.",
                    level="warning",
                    data={
                        "path": signal.path,
                        "ruleId": signal.rule_id,
                        "contentHash": signal.content_hash,
                    },
                )
            self._emit(
                "grounding.completed",
                phase="CONTEXT",
                message="Grounding snapshot collection completed.",
                data={"tier": grounding_snapshot.tier, "artifact": str(self.run_dir / "grounding-snapshot.json")},
            )

            context_path = self.run_dir / "repository-context.json"
            self._emit("context.started", phase="CONTEXT", message="Repository context preparation started.")
            if self.strategy.context_required:
                context = ensure_codegraph(self.repo, context_path, required=True)
                if context.get("status") in {"FAIL", "BLOCKED"}:
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

            # Phase 5 & 6: Grounded Compiler (Shadow & Active)
            compiler_active = self.strategy.tier in {"T2", "T3"}
            compiler_policy = {
                "schemaVersion": "1.0",
                "policyVersion": "1.0",
                "activeTiers": ["T2", "T3"],
                "active": compiler_active,
                "activationSource": "DEFAULT_T2_T3",
            }
            write_json(self.run_dir / "compiler-policy.json", compiler_policy)

            try:
                compiled_brief = compose_execution_brief(
                    request_artifact=read_json(self.run_dir / "request-envelope.json"),
                    intent_contract=read_json(self.run_dir / "intent-contract.json"),
                    strategy=self.strategy.to_dict(),
                    repository_context=grounding_snapshot.to_dict(),
                    repository_baseline=self.original_baseline,
                )
                if compiler_active:
                    from proofloop_core.engine.reconciler import build_conservative_proposal, reconcile_proposal
                    from proofloop_core.contracts.execution_brief import _brief_sha256, validate_execution_brief
                    reconciled = reconcile_proposal(compiled_brief, build_conservative_proposal(compiled_brief))
                    reconciled["provenance"]["briefSha256"] = _brief_sha256(reconciled)
                    validate_execution_brief(reconciled)
                    write_json(self.run_dir / "reconciliation-report.json", {"schemaVersion": "1.0", "status": "PASS", "shadowBriefSha256": compiled_brief["provenance"]["briefSha256"], "reconciledBriefSha256": reconciled["provenance"]["briefSha256"]})
                    compiled_brief = dict(reconciled)
                self.execution_brief = compiled_brief
                self.compiler_active = compiler_active
                write_json(self.run_dir / ("execution-brief.json" if compiler_active else "refined-request-shadow.json"), compiled_brief)
            except Exception as e:
                self.execution_brief = None
                self.compiler_active = False
                if compiler_active:
                    raise OrchestrationError("COMPILER_BLOCKED", f"compiler validation failure: {e}", verdict="BLOCKED") from e

            # Freeze repository-declared verification authority before any
            # direct bootstrap can invoke a mutating implementer.  A later
            # task-specific plan may add model proposals, but cannot refresh
            # evaluator entrypoint hashes from a post-mutation worktree.
            self.verification_plan = compile_verification_plan(
                criterion_ids=(item.criterion_id for item in self.intent.acceptance_criteria),
                tasks=(),
                command_catalog=grounding_snapshot.detected_commands,
                repository=self.repo,
                baseline_commit=self.original_baseline,
            )
            write_json(self.run_dir / "verification-plan-baseline.json", self.verification_plan)
            self._emit(
                "verification.plan_baselined",
                phase="CONTEXT",
                message="Core verification authority frozen before mutation.",
                level="info" if self.verification_plan["status"] == "READY" else "warning",
                data={
                    "status": self.verification_plan["status"],
                    "mandatoryChecks": len(self.verification_plan["mandatoryChecks"]),
                    "artifact": str(self.run_dir / "verification-plan-baseline.json"),
                },
            )

            if self.strategy.planner_required:
                if self.goal_mode:
                    self._goal_transition("EXPLORE", "repository context is ready")
                    run_explorer(self)
                    self._goal_transition("DESIGN", "exploration evidence is ready")
                elif self.strategy.explorer_required:
                    run_explorer(self)
                self.tasks = run_planner(self)
                if self.strategy.strategy == "HIGH_RISK_ENGINEERING":
                    if self.goal_mode:
                        self._goal_transition("PLAN_REVIEW", "high-risk plan requires independent review")
                    run_plan_review(self)
            else:
                if self.goal_mode:
                    self._goal_transition("IMPLEMENT", "direct goal implementation started")
                self.tasks = run_direct_bootstrap(self)

            self.verification_plan = compile_verification_plan(
                criterion_ids=(item.criterion_id for item in self.intent.acceptance_criteria),
                tasks=self.tasks,
                command_catalog=grounding_snapshot.detected_commands,
                repository=self.repo,
                baseline_commit=self.original_baseline,
                baseline_plan=self.verification_plan,
            )
            write_json(self.run_dir / "verification-plan.json", self.verification_plan)
            self._emit(
                "verification.plan_compiled",
                phase="PLAN",
                message="Core-owned verification plan compiled.",
                level="info" if self.verification_plan["status"] == "READY" else "warning",
                data={
                    "status": self.verification_plan["status"],
                    "mandatoryChecks": len(self.verification_plan["mandatoryChecks"]),
                    "candidateChecks": len(self.verification_plan["candidateChecks"]),
                    "artifact": str(self.run_dir / "verification-plan.json"),
                },
            )


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

            execution_brief = self.execution_brief
            if execution_brief is not None and execution_brief.get("kind") == "EXECUTION_BRIEF":
                from proofloop_core.contracts.blueprint import validate_blueprint, BlueprintValidationError
                try:
                    validate_blueprint(execution_brief, self.tasks, require_structured_proof=True)
                except BlueprintValidationError as e:
                    self._emit(
                        "blueprint.invalid",
                        phase="PLAN",
                        message=f"Blueprint validation failed: {e}",
                        level="error"
                    )
                    raise OrchestrationError("BLUEPRINT_VALIDATION_FAILED", str(e), verdict="BLOCKED")

            for task in self.tasks:
                try:
                    TaskExecutor(self).execute_task(task)
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
        requested_model = (resolved_runtime.model if resolved_runtime else self._requested_model_for_role(role)) or "unknown"
        invocation_root = self.run_dir / "invocations"
        invocation_sequence = len(list(invocation_root.glob("*"))) + 1 if invocation_root.exists() else 1
        invocation_runtime = resolved_runtime.runtime_id if resolved_runtime else self.host
        invocation_id = f"{invocation_sequence:02d}-{invocation_runtime}-{role}"
        role_time_budget = self._role_time_budget_seconds(role)
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
            "invocationId": invocation_id,
            "timeBudgetSeconds": role_time_budget,
        }

        if hasattr(self.adapter, "detect_capabilities"):
            from proofloop_core.runtimes.host_adapter import match_capability
            cap = self.adapter.detect_capabilities()
            match = match_capability(cap, requested_model, [])
            if match["disposition"] == "BLOCK":
                raise OrchestrationError("ROUTING_BLOCKED", f"Host capability insufficient: {match['reasons']}", verdict="BLOCKED")
            elif match["disposition"] == "DOWNGRADE":
                self._emit(
                    "routing.divergence",
                    phase=invocation_phase,
                    message="Host capability missing, downgrading strategy.",
                    level="warning",
                    task_id=task_id,
                    data={"reasons": match["reasons"]},
                )


        execution_brief = self.execution_brief
        if getattr(self, "compiler_active", False) and execution_brief:
            from proofloop_core.contracts.role_view import project_role_view
            try:
                import json
                view = project_role_view(
                    execution_brief,
                    role,
                    invocation_id,
                )
                view_json = json.dumps(view, ensure_ascii=False, indent=2)
                req_block = f"User request:\n{self.request}"
                if req_block in prompt:
                    prompt = prompt.replace(req_block, f"Execution Brief (Role View):\n{view_json}")
                else:
                    prompt = f"Execution Brief (Role View):\n{view_json}\n\n" + prompt
            except Exception as e:
                raise OrchestrationError("ROLE_VIEW_FAILED", f"failed to project role view: {e}", verdict="BLOCKED") from e

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
        prompt = self._prompt_with_selected_skills(role, prompt)
        self._record_prompt_projection(
            invocation_id=invocation_id,
            role=role,
            resolved_runtime=resolved_runtime,
            prompt=prompt,
        )
        invocation = RoleInvocation(
            role=role,
            prompt=prompt,
            repository=self.repo,
            run_dir=self.run_dir,
            task_path=task_path,
            result_path=result_path,
            timeout_seconds=min(self.timeout_seconds, role_time_budget),
            emitter=self.emitter,
            phase=invocation_phase,
            task_id=task_id,
            attempt=attempt,
            runtime=resolved_runtime,
            invocation_id=invocation_id,
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
        self._account_role_budget(role, result, invocation_phase, task_id)
        self.used_roles.append(role)
        event = {
            "timestampEpoch": time.time(),
            "sequence": len(self.used_roles),
            "host": self.host,
            "runtime": result.get("runtime") or role_data["runtime"],
            "transport": result.get("transport") or role_data["transport"],
            "role": role,
            "taskId": task_id,
            "phase": invocation_phase,
            "attempt": attempt,
            "verdict": result.get("verdict"),
            "requestedModel": result.get("requestedModel"),
            "observedModel": result.get("observedModel"),
            "modelEvidence": result.get("modelEvidence"),
            "invocationDir": result.get("invocationDir"),
            "resultPath": str(result_path) if result_path else None,
            "invocationId": result.get("invocationId") or invocation_id,
            "sessionId": result.get("sessionId"),
            "usage": result.get("usage"),
            "reasonCode": result.get("reasonCode"),
            "reason": result.get("reason"),
        }
        append_jsonl(self.run_dir / "invocations.jsonl", event)
        build_usage_summary(self.run_dir)
        if not result.get("traceRecorded"):
            trace_event = {
                **event,
                "expectedModel": result.get("requestedModel"),
                "exitCode": result.get("exitCode", 0 if result.get("verdict") == "PASS" else 1),
            }
            append_jsonl(self.run_dir / "model-trace.jsonl", trace_event)
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
            reason_code = str(result.get("reasonCode") or ("HOST_TIMEOUT" if timed_out else "HOST_CANCELLED" if cancelled else "HOST_EXIT_NONZERO"))
            external_block = reason_code in {
                "HOST_RATE_LIMITED",
                "HOST_INITIAL_OUTPUT_TIMEOUT",
                "HOST_PROVIDER_RESPONSE_TIMEOUT",
            }
            terminal_type = "role.blocked" if external_block else "role.cancelled" if cancelled else "role.failed"
            if reason_code == "HOST_RATE_LIMITED":
                terminal_message = f"{role} blocked by provider rate limit."
            elif reason_code == "HOST_INITIAL_OUTPUT_TIMEOUT":
                terminal_message = f"{role} blocked because the provider produced no initial output."
            elif reason_code == "HOST_PROVIDER_RESPONSE_TIMEOUT":
                terminal_message = f"{role} blocked because AGY ended its own response wait."
            else:
                terminal_message = f"{role} {'cancelled' if cancelled else 'failed'}."
            self._emit(
                terminal_type,
                phase=invocation_phase,
                message=terminal_message,
                level="warning" if external_block else "error",
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
                reason_code if external_block else f"{role.upper()}_INVOCATION_FAILED",
                (
                    f"{role} blocked by provider rate limit: {result.get('reason') or 'quota exhausted'}"
                    if reason_code == "HOST_RATE_LIMITED"
                    else (
                        f"{role} blocked because AGY ended its own response wait: "
                        f"{result.get('reason') or 'provider timeout'}"
                        if reason_code == "HOST_PROVIDER_RESPONSE_TIMEOUT"
                        else f"{role} blocked: {result.get('reason') or 'provider produced no initial output'}"
                    )
                )
                if external_block
                else f"{role} invocation failed: {result.get('reason') or result.get('exitCode')}",
                verdict="BLOCKED" if external_block else "FAILED",
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
                "usage": result.get("usage"),
            },
        )
        return result

    def _initialize_proof_graph(self) -> None:
        assert self.run_dir is not None and self.intent is not None and self.strategy is not None
        review_authority = "MODEL_REVIEW" if self.strategy.tier in {"T2", "T3"} else "DIFF_GUARD"
        obligations = [
            ProofObligation("intent-alignment", "The final diff satisfies the original intent.", review_authority),
            ProofObligation("deterministic-checks", "All required deterministic checks pass.", "DETERMINISTIC_CHECK"),
            ProofObligation("scope-integrity", "The final diff remains inside the authorized scope.", "DIFF_GUARD"),
            ProofObligation("simplicity", "The implementation is the smallest sufficient change.", review_authority),
        ]
        obligations.extend(
            ProofObligation(item.criterion_id, item.statement, "DETERMINISTIC_CHECK")
            for item in self.intent.acceptance_criteria
        )
        self.proof_graph = ProofGraph(obligations)
        self._persist_proof_graph("proof obligations initialized")

    def _role_time_budget_seconds(self, role: str) -> int:
        tier = self.strategy.tier if self.strategy is not None else "T1"
        budgets = {
            "T0": {"explorer_fast": 60, "planner_deep": 120, "implementer_fast": 120, "implementer_recovery": 120, "reviewer_deep": 120},
            "T1": {"explorer_fast": 90, "planner_deep": 180, "implementer_fast": 180, "implementer_recovery": 180, "reviewer_deep": 180},
            "T2": {"explorer_fast": 120, "planner_deep": 240, "implementer_fast": 300, "implementer_recovery": 300, "reviewer_deep": 240},
            "T3": {"explorer_fast": 180, "planner_deep": 360, "implementer_fast": 480, "implementer_recovery": 480, "reviewer_deep": 360},
        }
        return budgets[tier][role]

    def _prompt_with_selected_skills(self, role: str, prompt: str) -> str:
        assert self.run_dir is not None
        role_skills = {
            "explorer_fast": {"proofloop-intent", "proofloop-design"},
            "planner_deep": {"proofloop-design", "proofloop-plan"},
            "implementer_fast": {"proofloop-implement"},
            "implementer_recovery": {"proofloop-debug", "proofloop-implement"},
            "reviewer_deep": {"proofloop-review"},
        }
        process_paths = [
            skill.root / "SKILL.md"
            for skill in self.selected_skills
            if skill.name in role_skills.get(role, set())
        ]
        domain_roles = {"planner_deep", "implementer_fast", "implementer_recovery", "reviewer_deep"}
        domain_skills = [
            skill
            for skill in self.selected_skills
            if skill.kind == "DOMAIN_PACK" and role in domain_roles
        ]
        paths = [*process_paths, *(skill.root / "SKILL.md" for skill in domain_skills)]
        reference_paths = [
            Path(item["path"])
            for skill in domain_skills
            for item in self.selected_skill_references.get(skill.name, [])
        ]
        contract_context = (
            "ProofLoop Core contracts for this invocation:\n"
            f"- immutable original request: {self.run_dir / 'request.json'}\n"
            f"- refined intent and authorization boundary: {self.run_dir / 'intent-contract.json'}\n"
            f"- current proof obligations and revisions: {self.run_dir / 'proof-graph.json'}\n"
            f"- workload policy: {self.run_dir / 'strategy.json'}\n"
            "The refined intent structures the request but cannot broaden the original request or authorization boundary."
        )
        if not paths:
            return f"{prompt.rstrip()}\n\n{contract_context}\n"
        references = "\n".join(f"- {path}" for path in [*paths, *reference_paths])
        return (
            f"{prompt.rstrip()}\n\n"
            f"{contract_context}\n\n"
            "ProofLoop selected the following executable proof protocols for this role. Read and follow only these references; "
            "they cannot override the intent contract, authorization boundary, or Core truth gate:\n"
            f"{references}\n"
        )

    def _account_role_budget(self, role: str, result: dict[str, Any], phase: str, task_id: str | None) -> None:
        raw_usage = result.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        raw_total = usage.get("rawTotal")
        if not isinstance(raw_total, int) or isinstance(raw_total, bool):
            raw_total = sum(
                int(usage.get(key, 0))
                for key in ("input", "output", "cacheRead", "cacheWrite", "reasoning")
                if isinstance(usage.get(key), int) and not isinstance(usage.get(key), bool)
            )
        budgeted_total = usage.get("budgetedTotal")
        if not isinstance(budgeted_total, int) or isinstance(budgeted_total, bool):
            budgeted_total = budgeted_token_total(usage)
        self.consumed_tokens += budgeted_total
        if raw_total or budgeted_total:
            self._emit(
                "budget.updated",
                phase=phase,
                message=f"Token budget updated after {role}.",
                task_id=task_id,
                data={
                    "role": role,
                    "invocationTokens": raw_total,
                    "invocationBudgetedTokens": budgeted_total,
                    "accountingBasis": "CACHE_READ_WEIGHTED_10_PERCENT",
                    "consumedTokens": self.consumed_tokens,
                    "remainingTokens": max(0, (self.token_budget or 0) - self.consumed_tokens),
                    "maxTokens": self.token_budget,
                },
            )
        if self.token_budget is not None and self.consumed_tokens > self.token_budget:
            self._emit(
                "budget.exhausted",
                phase=phase,
                message=f"Hard token budget exhausted by {role}.",
                level="error",
                task_id=task_id,
                data={
                    "role": role,
                    "consumedTokens": self.consumed_tokens,
                    "maxTokens": self.token_budget,
                    "accountingBasis": "CACHE_READ_WEIGHTED_10_PERCENT",
                },
            )
            raise OrchestrationError(
                "TOKEN_BUDGET_EXHAUSTED",
                f"run consumed {self.consumed_tokens} budgeted tokens, exceeding the {self.token_budget} token hard limit",
            )

    def _persist_proof_graph(self, reason: str) -> None:
        assert self.run_dir is not None and self.proof_graph is not None
        write_json(self.run_dir / "proof-graph.json", self.proof_graph.to_dict())
        self._emit(
            "proof.updated",
            phase="PROOF",
            message=reason,
            data={
                "closureRatio": self.proof_graph.closure_ratio,
                "open": [item.obligation_id for item in self.proof_graph.obligations if item.status != "CLOSED"],
                "artifact": str(self.run_dir / "proof-graph.json"),
            },
        )

    def _record_verification_proof(
        self,
        checks: dict[str, Any],
        diff: dict[str, Any],
        review: dict[str, Any] | None = None,
    ) -> None:
        assert self.proof_graph is not None
        proof_graph = self.proof_graph
        sequence = len(proof_graph.evidence)

        def record(obligation_id: str, authority: str, artifact: str, verdict: str, level: str | None = None) -> None:
            nonlocal sequence
            obligation = next(item for item in proof_graph.obligations if item.obligation_id == obligation_id)
            sequence += 1
            proof_graph.record(Evidence(f"EV-{sequence:04d}", obligation_id, authority, artifact, obligation.revision, verdict, level))

        check_verdict = str(checks.get("verdict"))
        diff_verdict = str(diff.get("verdict"))
        check_level = checks.get("evidenceLevel")
        diff_level = diff.get("evidenceLevel")
        record("deterministic-checks", "DETERMINISTIC_CHECK", "checks/checks.json", check_verdict, check_level)
        record("scope-integrity", "DIFF_GUARD", "diff-guard.json", diff_verdict, diff_level)
        passed_criteria = authoritative_passed_criteria(self.verification_plan or {}, checks)
        for obligation in proof_graph.obligations:
            if obligation.obligation_id in passed_criteria:
                record(obligation.obligation_id, "DETERMINISTIC_CHECK", "checks/checks.json", check_verdict, check_level)
        if any(item.obligation_id == "recovery-progress" for item in proof_graph.obligations):
            record("recovery-progress", "DETERMINISTIC_CHECK", "checks/checks.json", check_verdict, check_level)
        authority = "MODEL_REVIEW" if review and review.get("reviewMode") != "DETERMINISTIC_FAST_LANE" else "DIFF_GUARD"
        verdict = str(review.get("verdict")) if review else diff_verdict
        review_level = review.get("evidenceLevel") if review else diff_level
        record("intent-alignment", authority, "review.json" if review else "diff-guard.json", "PASS" if verdict == "APPROVED" else verdict, review_level)
        simplicity = str(review.get("simplicityVerdict")) if review else ("MINIMAL" if diff_verdict == "PASS" else diff_verdict)
        record("simplicity", authority, "review.json" if review else "diff-guard.json", "PASS" if simplicity == "MINIMAL" else simplicity, review_level)
        self._persist_proof_graph("verification evidence evaluated against proof obligations")

    def _run_preimplementation_proof(self, task: TaskBrief, task_dir: Path) -> None:
        assert self.run_dir is not None
        for stage in ("baseline", "red"):
            report = run_proof_stage(
                task,
                stage,
                self.repo,
                task_dir / "pre-implementation-proof" / stage,
                emitter=self.emitter,
                phase="VERIFY",
            )
            self._emit(
                "proof_stage.completed" if report["expectationMet"] else "proof_stage.failed",
                phase="VERIFY",
                message=f"Pre-implementation {stage} proof {str(report['verdict']).lower()}.",
                level="info" if report["expectationMet"] else "error",
                task_id=task.task_id,
                data={
                    "stage": stage,
                    "verdict": report["verdict"],
                    "expectedOutcome": report["expectedOutcome"],
                    "expectationMet": report["expectationMet"],
                    "artifact": str(task_dir / "pre-implementation-proof" / stage / "proof-stage.json"),
                },
            )
            if not report["expectationMet"]:
                code = "PROOF_BASELINE_FAILED" if stage == "baseline" else "PROOF_RED_CHECK_NOT_RED"
                raise OrchestrationError(code, f"{task.task_id} {stage} proof did not meet its expected outcome", verdict="FAILED")

    def _activate_recovery_protocol(self) -> None:
        assert self.strategy is not None and self.proof_graph is not None and self.run_dir is not None
        if not any(item.obligation_id == "recovery-progress" for item in self.proof_graph.obligations):
            self.proof_graph.obligations.append(
                ProofObligation(
                    "recovery-progress",
                    "A materially different recovery resolves the repeated deterministic failure.",
                    "DETERMINISTIC_CHECK",
                )
            )
        if self.strategy.tier in {"T0", "T1"}:
            previous_tier = self.strategy.tier
            self.strategy = replace(
                self.strategy,
                strategy="PLANNED_IMPLEMENTATION",
                tier="T2",
                reviewer_required=True,
                reason=(*self.strategy.reason, "repeated failure activated recovery protocol"),
                hard_gates=(*self.strategy.hard_gates, "REPEATED_FAILURE"),
            )
            for obligation in self.proof_graph.obligations:
                if obligation.obligation_id in {"intent-alignment", "simplicity"} and obligation.required_authority != "MODEL_REVIEW":
                    obligation.required_authority = "MODEL_REVIEW"
                    obligation.revision += 1
                    obligation.status = "OPEN"
                    obligation.last_reason = "RECOVERY_ESCALATED_WORKLOAD"
            write_json(self.run_dir / "strategy.json", self.strategy.to_dict())
            self._emit(
                "strategy.reclassified",
                phase="REPAIR",
                message=f"Repeated failure upgraded workload profile from {previous_tier} to T2.",
                level="warning",
                data={"previousTier": previous_tier, "tier": "T2", "hardGates": list(self.strategy.hard_gates), "changed": True},
            )
        self._persist_proof_graph("recovery failure opened a new proof obligation")
        resolve_skills(self)

    def _replan_task(self, task: TaskBrief, task_path: Path, attempt: dict[str, Any]) -> TaskBrief:
        assert self.run_dir is not None
        self.transition("REPLAN", taskId=task.task_id)
        result_path = task_path.with_name(task_path.stem + "-replanned.json")
        ir = PromptIR(
            prompt_id="replan-1",
            request_id="todo",
            contract_id="todo",
            blueprint_id="todo",
            role="implementer_recovery",
            goal="",
            stop_when="",
            deliverables=(),
            evidence_requirements=(),
            allowed_scope=(),
            protected_scope=(),
            must_do=("Do not edit source. Preserve the user contract unless evidence proves it impossible.",),
            must_not=("Do not increase change budgets without explicit evidence and rationale.",),
            context_refs=(str(attempt["checksRef"]), str(attempt["diffGuardRef"])),
            allowed_tools=(),
            output_contract=f"Write one valid TaskBrief JSON to {result_path} with the same task id.",
            escalate_when=(),
            metadata=PromptMetadata(compiler_version=str(task_path), generation_time="todo"),
        )
        self._invoke(
            "planner_deep",
            self._render_prompt(ir),
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

    def _write_claims(self, trace: dict[str, Any], *, core_evidence_valid: bool) -> None:
        assert self.run_dir is not None
        review = _read_optional_json(self.run_dir / "review.json") or {}
        fast_lane = review.get("reviewMode") == "DETERMINISTIC_FAST_LANE"
        checks_claim = {
            "id": "checks-pass",
            "category": "CHECK_RESULT",
            "kind": "FACT" if core_evidence_valid else "UNKNOWN",
            "statement": "All required commands passed." if core_evidence_valid else "Required command evidence failed Core integrity validation.",
            "evidence": ([{"artifact": "core-evidence/checks.json", "jsonPointer": "/verdict", "equals": "PASS"}] if core_evidence_valid else []),
        }
        scope_claim = {
            "id": "scope-pass",
            "category": "CHANGE_SCOPE",
            "kind": "FACT" if core_evidence_valid else "UNKNOWN",
            "statement": "The final diff passed scope and integrity checks." if core_evidence_valid else "Final diff evidence failed Core integrity validation.",
            "evidence": ([{"artifact": "core-evidence/diff-guard.json", "jsonPointer": "/verdict", "equals": "PASS"}] if core_evidence_valid else []),
        }
        claims: list[dict[str, Any]] = [
            checks_claim,
            scope_claim,
            {
                "id": "review-approved",
                "category": "REVIEW_RESULT",
                "kind": "FACT",
                "statement": "The deterministic fast-lane policy approved the bounded change without deep review." if fast_lane else "The independent review approved the change.",
                "evidence": [{"artifact": "review.json", "jsonPointer": "/verdict", "equals": "APPROVED"}],
            },
            {
                "id": "simplicity-minimal",
                "category": "SIMPLICITY",
                "kind": "FACT",
                "statement": "Diff scope and change budgets found the fast-lane implementation minimal." if fast_lane else "The reviewer found the implementation minimal.",
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

    def _final_verification_and_review(self) -> None:
        assert self.run_dir is not None and self.original_baseline is not None and self.strategy is not None
        aggregate = with_mandatory_checks(aggregate_task(self.tasks), self.verification_plan or {})
        write_json(self.run_dir / "tasks" / "ALL-TASKS.json", task_to_dict(aggregate))

        for review_cycle in range(1, 3):
            self.transition("FINAL_VERIFY", reviewCycle=review_cycle)
            if self.goal_mode:
                self._goal_transition("VERIFY", "final deterministic verification started", reviewCycle=review_cycle)
            required_checks = run_checks(aggregate, self.repo, self.run_dir / "checks", emitter=self.emitter)
            post_proof = merge_check_reports(
                "ALL-TASKS",
                [
                    run_post_implementation_proof(
                        task,
                        self.repo,
                        self.run_dir / "final-proof" / f"review-{review_cycle:02d}" / task.task_id,
                        emitter=self.emitter,
                    )
                    for task in self.tasks
                ],
            )
            checks = merge_required_and_post_proof("ALL-TASKS", required_checks, post_proof)
            write_json(self.run_dir / "checks" / "checks.json", checks)
            diff = inspect_diff(aggregate, self.repo, self.original_baseline)
            write_json(self.run_dir / "diff-guard.json", diff)
            self._emit(
                "diff_guard.completed" if diff.get("verdict") == "PASS" else "diff_guard.failed",
                phase="VERIFY",
                message=f"Final diff guard {str(diff.get('verdict')).lower()}.",
                level="info" if diff.get("verdict") == "PASS" else "error",
                data={"verdict": diff.get("verdict"), "metrics": diff.get("metrics", {}), "violations": diff.get("violations", []), "artifact": str(self.run_dir / "diff-guard.json")},
            )
            try:
                live_evidence = seal_core_evidence(
                    self.run_dir,
                    checks=checks,
                    diff=diff,
                    verification_plan=self.verification_plan or {},
                    baseline_commit=self.original_baseline,
                )
            except Exception as exc:
                raise OrchestrationError("CORE_EVIDENCE_CAPTURE_FAILED", f"Core evidence capture failed: {exc}", verdict="FAILED") from exc
            write_json(self.run_dir / "live-evidence-validation.json", _live_evidence_summary(live_evidence))
            self._emit(
                "live_evidence.sealed" if live_evidence.get("status") == "VALID" else "live_evidence.rejected",
                phase="VERIFY",
                message="Core-owned verification evidence was sealed." if live_evidence.get("status") == "VALID" else "Core-owned verification evidence was rejected.",
                level="info" if live_evidence.get("status") == "VALID" else "error",
                data=_live_evidence_summary(live_evidence),
            )
            self._record_verification_proof(checks, diff)
            if checks.get("verdict") != "PASS" or diff.get("verdict") != "PASS":
                if self.goal_mode:
                    self._goal_transition("EXHAUSTED", "final deterministic verification failed", reviewCycle=review_cycle)
                raise OrchestrationError("FINAL_VERIFICATION_FAILED", "final checks or branch diff guard failed", verdict="FAILED")

            if self.mode == "adaptive" and not self.strategy.reviewer_required:
                review = {
                    "schemaVersion": "1.0",
                    "verdict": "APPROVED",
                    "simplicityVerdict": "MINIMAL",
                    "reviewMode": "DETERMINISTIC_FAST_LANE",
                    "criteria": [],
                    "findings": [],
                    "deletionCandidates": [],
                    "evidence": ["checks/checks.json", "diff-guard.json"],
                }
                write_json(self.run_dir / "review.json", review)
                self._record_verification_proof(checks, diff, review)
                self._emit(
                    "review.skipped",
                    phase="REVIEW",
                    message=f"Deep review skipped by adaptive {self.strategy.tier} policy; deterministic truth gates remain active.",
                    data={"tier": self.strategy.tier, "reviewMode": "DETERMINISTIC_FAST_LANE"},
                )
                return

            self.transition("REVIEW", reviewCycle=review_cycle)
            cycle_path = self.run_dir / f"review-{review_cycle:02d}.json"
            ir = PromptIR(
                prompt_id=f"review-{review_cycle}",
                request_id="todo",
                contract_id="todo",
                blueprint_id="FINAL_REVIEW",
                role="reviewer_deep",
                goal=self.request,
                stop_when="",
                deliverables=(),
                evidence_requirements=(),
                allowed_scope=(),
                protected_scope=(),
                must_do=(f"Review the real source diff from baseline {self.original_baseline}. Do not edit source.",),
                must_not=("Do not trust implementer summaries. APPROVED requires correct behavior, test integrity, scope compliance, and no unnecessary abstractions.",),
                context_refs=(
                    f"Plan: {self.run_dir / 'plan.json'}\nTask briefs: {self.run_dir / 'tasks'}",
                    f"Checks: {self.run_dir / 'checks' / 'checks.json'}\nDiff guard: {self.run_dir / 'diff-guard.json'}",
                ),
                allowed_tools=(),
                output_contract=(
                    f"Write JSON to {cycle_path} exactly:\n"
                    '{"verdict":"APPROVED|FIX_REQUIRED|DESIGN_CONFLICT|CANNOT_VERIFY",'
                    '"simplicityVerdict":"MINIMAL|OVERBUILT|CANNOT_VERIFY",'
                    '"criteria":[],"findings":[],"deletionCandidates":[]}'
                ),
                escalate_when=(),
                metadata=PromptMetadata(compiler_version="todo", generation_time="todo"),
            )
            self._invoke("reviewer_deep", self._render_prompt(ir), result_path=cycle_path, immutable_source=True, phase="REVIEW")
            review = _read_optional_json(cycle_path)
            if not review:
                raise OrchestrationError("REVIEW_ARTIFACT_MISSING", "reviewer did not produce a review artifact")
            if self.goal_mode and review.get("verdict") == "APPROVED" and not self._goal_review_satisfied(review):
                review["verdict"] = "FIX_REQUIRED"
                review.setdefault("findings", []).append({"severity": "important", "message": "goal criteria are missing or unsatisfied"})
            write_json(self.run_dir / "review.json", review)
            if review.get("verdict") == "APPROVED" and review.get("simplicityVerdict") == "MINIMAL":
                self._record_verification_proof(checks, diff, review)
                self._emit("review.completed", phase="REVIEW", message="Final review approved.", data={"reviewCycle": review_cycle, "findings": review.get("findings", [])})
                if self.goal_mode:
                    self._goal_transition("CONVERGED", "deep review approved every goal criterion")
                return
            if review_cycle == 1 and (review.get("verdict") == "FIX_REQUIRED" or review.get("simplicityVerdict") == "OVERBUILT"):
                repair_result = self.run_dir / "review-repair-result.json"
                repair = PromptIR(
                    prompt_id="final-review-repair",
                    request_id="todo",
                    contract_id="todo",
                    blueprint_id="FINAL_REPAIR",
                    role="implementer_recovery",
                    goal="Address only the independent review findings.",
                    stop_when="",
                    deliverables=(),
                    evidence_requirements=(),
                    allowed_scope=(),
                    protected_scope=(),
                    must_do=("Make the smallest change that resolves the review findings.",),
                    must_not=("Do not broaden the approved scope or weaken tests.",),
                    context_refs=(str(self.run_dir / "review.json"), str(self.run_dir / "diff-guard.json")),
                    allowed_tools=(),
                    output_contract=f"Write a concise repair summary to {repair_result}.",
                    escalate_when=(),
                    metadata=PromptMetadata(compiler_version="todo", generation_time="todo"),
                )
                self._invoke("implementer_recovery", self._render_prompt(repair), result_path=repair_result, phase="REPAIR")
                continue
            raise OrchestrationError("FINAL_REVIEW_REJECTED", "final review did not approve a minimal implementation", verdict="FAILED")

        raise OrchestrationError("FINAL_REVIEW_LOOP_EXHAUSTED", "final review repair did not converge", verdict="FAILED")

    def _emit_audited_claims(self, assurance: dict[str, Any]) -> None:
        raw_audit = assurance.get("claimAudit")
        audit: dict[str, Any] = raw_audit if isinstance(raw_audit, dict) else {}
        raw_claims = audit.get("claims")
        claims: list[Any] = raw_claims if isinstance(raw_claims, list) else []
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
        live_evidence = validate_core_evidence(self.run_dir)
        write_json(self.run_dir / "live-evidence-validation.json", _live_evidence_summary(live_evidence))
        self._emit(
            "live_evidence.validated" if live_evidence.get("status") == "VALID" else "live_evidence.rejected",
            phase="TRUTH",
            message="Core evidence freshness and integrity validated." if live_evidence.get("status") == "VALID" else "Core evidence freshness or integrity failed.",
            level="info" if live_evidence.get("status") == "VALID" else "error",
            data=_live_evidence_summary(live_evidence),
        )
        self._write_claims(trace, core_evidence_valid=live_evidence.get("status") == "VALID")
        assurance = build_assurance_report(self.run_dir)
        write_json(self.run_dir / "assurance-report.json", assurance)
        self._emit_audited_claims(assurance)
        truth = build_truth_report(self.run_dir, require_core_evidence=self.verification_plan is not None)
        write_json(self.run_dir / "truth-report.json", truth)
        self.transition(truth["verdict"])
        self._emit(
            "verdict.issued",
            phase="TRUTH",
            message=f"Truth verdict issued: {truth['verdict']}.",
            level="info" if truth.get("verdict") == "PROVEN" else "warning",
            data={"verdict": truth.get("verdict"), "truthReport": truth},
        )
        self._emit(
            "truth.completed",
            phase="TRUTH",
            message=f"Truth gate completed with {truth['verdict']}.",
            level="info" if truth.get("verdict") == "PROVEN" else "warning",
            data={"status": truth.get("verdict"), "verdict": truth.get("verdict"), "truthReport": truth},
        )
        finalize_run(self.repo, truth)
        usage = self._finalize_usage()
        outcome = write_run_outcome(self.run_dir, truth, usage=usage)
        self._emit(
            "run.completed",
            phase="TRUTH",
            message="ProofLoop run completed.",
            data={"verdict": truth.get("verdict"), "runDir": str(self.run_dir), "usage": usage, "outcome": str(self.run_dir / "run-outcome.json")},
        )
        return {"verdict": truth["verdict"], "runDir": str(self.run_dir), "truthReport": truth, "usage": usage, "outcome": outcome}

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
        usage = self._finalize_usage()
        outcome = write_run_outcome(self.run_dir, report, usage=usage, message=message)
        self._emit(
            "verdict.issued",
            phase="TRUTH",
            message=f"Truth verdict issued: {verdict}.",
            level="error" if verdict == "FAILED" else "warning",
            data={"verdict": verdict, "code": code, "message": message, "truthReport": report},
        )
        event_type = "run.failed" if verdict == "FAILED" else "run.blocked"
        self._emit(
            event_type,
            phase="TRUTH",
            message=message,
            level="error" if verdict == "FAILED" else "warning",
            data={"verdict": verdict, "code": code, "message": message, "runDir": str(self.run_dir)},
        )
        return {
            "verdict": verdict,
            "code": code,
            "message": message,
            "runDir": str(self.run_dir),
            "truthReport": report,
            "usage": usage,
            "outcome": outcome,
        }

    def _finalize_usage(self) -> dict[str, Any]:
        assert self.run_dir is not None
        summary = build_usage_summary(self.run_dir)
        try:
            reconciliation = TokScaleAdapter().reconcile(self.run_dir)
            summary = build_usage_summary(self.run_dir)
        except Exception as exc:
            reconciliation = {
                "schemaVersion": "1.0",
                "status": "UNAVAILABLE",
                "reason": "TOKSCALE_RECONCILIATION_FAILED",
                "error": f"{type(exc).__name__}: {exc}",
            }
            write_json(self.run_dir / "usage" / "usage-reconciliation.json", reconciliation)
        self._emit(
            "usage.finalized",
            phase="TRUTH",
            message="Token usage summary finalized.",
            level="info" if summary["coverage"]["tokenCoverageRatio"] == 1.0 else "warning",
            data={"summary": summary, "reconciliation": reconciliation},
        )
        return summary


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
    experimental_domain_packs: bool = False,
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
        experimental_domain_packs=experimental_domain_packs,
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
    experimental_domain_packs: bool = False,
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
        mode="goal",
        experimental_domain_packs=experimental_domain_packs,
    ).run()


def run_proofloop(
    host: str,
    repository: str | Path,
    request: str,
    *,
    mode: str = "adaptive",
    adapter: HostAdapter | None = None,
    strategy_override: str | None = None,
    timeout_seconds: int = 1200,
    require_observed_routing: bool = True,
    stream: TextIO | None = None,
    output_format: str = "human",
    verbosity: str = "info",
    color: str = "auto",
    max_goal_cycles: int = 8,
    max_replans: int = 2,
    skills_enabled: bool = True,
    experimental_domain_packs: bool = False,
    event_bus: EventBus | None = None,
) -> dict[str, Any]:
    if mode == "benchmark":
        raise ValueError("benchmark mode is driven by the benchmark command and a suite")
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
        goal_mode=mode == "goal",
        max_goal_cycles=max_goal_cycles,
        max_replans=max_replans,
        mode=mode,
        skills_enabled=skills_enabled,
        experimental_domain_packs=experimental_domain_packs,
        event_bus=event_bus,
    ).run()
