from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, TYPE_CHECKING

from proofloop_core.context.io import read_json, write_json
from proofloop_core.contracts.execution_brief import (
    _brief_sha256,
    compose_execution_brief,
    validate_execution_brief,
)
from proofloop_core.contracts.role_view import project_role_view
from proofloop_core.engine.reconciler import build_conservative_proposal, reconcile_proposal
from proofloop_core.prompting.algebra import (
    INTENT_AUDIT,
    INTENT_MUTATE,
    RISK_T2,
    SURFACE_REPOSITORY,
    TemplatePolicy,
    compile_ir,
    merge_templates,
)
from proofloop_core.prompting.prompt_ir import PromptIR

if TYPE_CHECKING:
    from proofloop_core.contracts.task_brief import TaskBrief
    from proofloop_core.engine.orchestrator import ProofLoopOrchestrator

SCHEMA_VERSION = "1.0"
COMPILER_VERSION = "prompt-contract.v1"


class PromptContractError(ValueError):
    """Raised when prompt compilation or projection cannot be proven safe."""


@dataclass(frozen=True)
class PromptCompilation:
    request_id: str
    request_sha256: str
    intent_sha256: str
    strategy_sha256: str
    repository_context_sha256: str
    selected_template_ids: tuple[str, ...]
    template_set_sha256: str
    merged_policy_sha256: str
    execution_brief_sha256: str
    compiler_version: str = COMPILER_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "compilerVersion": self.compiler_version,
            "requestId": self.request_id,
            "requestSha256": self.request_sha256,
            "intentSha256": self.intent_sha256,
            "strategySha256": self.strategy_sha256,
            "repositoryContextSha256": self.repository_context_sha256,
            "selectedTemplateIds": list(self.selected_template_ids),
            "templateSetSha256": self.template_set_sha256,
            "mergedPolicySha256": self.merged_policy_sha256,
            "executionBriefSha256": self.execution_brief_sha256,
        }


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def select_templates(*, authority: str, tier: str) -> tuple[TemplatePolicy, ...]:
    """Select the existing versioned templates for one request.

    Selection is deterministic and deliberately small. Repository surface is
    always present because role prompts must be grounded in repository facts.
    Higher-risk tiers add the existing risk template; they do not switch to a
    parallel prompt system.
    """

    if authority == "read_only":
        selected: list[TemplatePolicy] = [INTENT_AUDIT, SURFACE_REPOSITORY]
    elif authority == "repository_mutation":
        selected = [INTENT_MUTATE, SURFACE_REPOSITORY]
    else:
        raise PromptContractError(f"unsupported intent authority: {authority}")
    if tier in {"T2", "T3"}:
        selected.append(RISK_T2)
    return tuple(selected)


def _validate_request_link(envelope: Mapping[str, Any], intent: Mapping[str, Any]) -> None:
    raw = envelope.get("rawText")
    if not isinstance(raw, str) or not raw.strip():
        raise PromptContractError("REQUEST_ENVELOPE_INVALID: rawText is missing")
    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if intent.get("originalRequest") != raw or intent.get("originalRequestHash") != expected:
        raise PromptContractError("REQUEST_ENVELOPE_INVALID: intent is detached from raw request")
    raw_hash = envelope.get("rawHash")
    if raw_hash not in {expected, f"sha256:{expected}"}:
        raise PromptContractError("REQUEST_ENVELOPE_INVALID: rawHash does not match rawText")


def _active_brief(
    *,
    envelope: Mapping[str, Any],
    intent: Mapping[str, Any],
    strategy: Mapping[str, Any],
    repository_context: Mapping[str, Any],
    repository_baseline: str,
) -> dict[str, Any]:
    shadow = compose_execution_brief(
        request_artifact=envelope,
        intent_contract=intent,
        strategy=strategy,
        repository_context=repository_context,
        repository_baseline=repository_baseline,
    )
    proposal = build_conservative_proposal(shadow)
    active = reconcile_proposal(shadow, proposal)
    active = copy.deepcopy(active)
    active["provenance"]["briefSha256"] = _brief_sha256(active)
    validate_execution_brief(active)
    return active


def compile_prompt_contract(
    *,
    request_envelope: Mapping[str, Any],
    intent_contract: Mapping[str, Any],
    strategy: Mapping[str, Any],
    repository_context: Mapping[str, Any],
    repository_baseline: str,
    authority: str,
    tier: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile one active execution brief and its traceable template artifact."""

    _validate_request_link(request_envelope, intent_contract)
    templates = select_templates(authority=authority, tier=tier)
    merged = merge_templates(list(templates))
    active = _active_brief(
        envelope=request_envelope,
        intent=intent_contract,
        strategy=strategy,
        repository_context=repository_context,
        repository_baseline=repository_baseline,
    )
    selected = tuple(template.id for template in templates)
    template_payload = [template.to_dict() for template in templates]
    compilation = PromptCompilation(
        request_id=str(request_envelope["requestId"]),
        request_sha256=hashlib.sha256(str(request_envelope["rawText"]).encode("utf-8")).hexdigest(),
        intent_sha256=canonical_sha256(dict(intent_contract)),
        strategy_sha256=canonical_sha256(dict(strategy)),
        repository_context_sha256=canonical_sha256(dict(repository_context)),
        selected_template_ids=selected,
        template_set_sha256=canonical_sha256(template_payload),
        merged_policy_sha256=canonical_sha256(merged.to_dict()),
        execution_brief_sha256=canonical_sha256(active),
    ).to_dict()
    compilation["mergedPolicy"] = merged.to_dict()
    compilation["selectedTemplates"] = template_payload
    return active, compilation


def ensure_active_prompt_contract(orchestrator: "ProofLoopOrchestrator") -> None:
    """Make the prompt compiler mandatory for every tier before role invocation."""

    if orchestrator.run_dir is None or orchestrator.intent is None or orchestrator.strategy is None:
        raise PromptContractError("PROMPT_CONTRACT_UNRESOLVED: run context is incomplete")
    root = orchestrator.run_dir
    existing = root / "prompt-compilation.json"
    active_path = root / "execution-brief.json"
    if existing.is_file() and active_path.is_file():
        active = read_json(active_path)
        validate_execution_brief(active)
        orchestrator.execution_brief = active
        orchestrator.compiler_active = True
        return

    envelope = read_json(root / "request-envelope.json")
    intent = read_json(root / "intent-contract.json")
    strategy = orchestrator.strategy.to_dict()
    context_path = root / "grounding-snapshot.json"
    if not context_path.exists():
        raise PromptContractError("PROMPT_CONTRACT_UNRESOLVED: grounding snapshot is missing")
    context = read_json(context_path)
    authority = getattr(orchestrator.intent_gate_result, "authority", None)
    authority_value = getattr(authority, "value", None)
    active, compilation = compile_prompt_contract(
        request_envelope=envelope,
        intent_contract=intent,
        strategy=strategy,
        repository_context=context,
        repository_baseline=str(orchestrator.original_baseline or "UNKNOWN"),
        authority=str(authority_value or "repository_mutation"),
        tier=str(orchestrator.strategy.tier),
    )
    write_json(active_path, active)
    write_json(existing, compilation)
    orchestrator.execution_brief = active
    orchestrator.compiler_active = True


def compile_role_ir(
    orchestrator: "ProofLoopOrchestrator",
    *,
    role: str,
    output_contract: str,
    must_do: Iterable[str] = (),
    must_not: Iterable[str] = (),
    context_refs: Iterable[str] = (),
    task: "TaskBrief | None" = None,
    stop_when: str = "",
    escalate_when: Iterable[str] = (),
) -> PromptIR:
    """Project the active prompt contract into one content-addressed PromptIR."""

    ensure_active_prompt_contract(orchestrator)
    assert orchestrator.execution_brief is not None and orchestrator.run_dir is not None
    invocation_seed = canonical_sha256(
        {
            "role": role,
            "executionBrief": canonical_sha256(orchestrator.execution_brief),
            "task": getattr(task, "task_id", None),
            "outputContract": output_contract,
            "mustDo": list(must_do),
            "mustNot": list(must_not),
            "contextRefs": list(context_refs),
        }
    )
    view = project_role_view(
        orchestrator.execution_brief,
        role,
        f"pending-{invocation_seed[:16]}",
    )
    task_scope: tuple[str, ...] = ()
    protected_scope: tuple[str, ...] = ()
    evidence_requirements: tuple[str, ...] = ()
    deliverables: tuple[str, ...] = ()
    if task is not None:
        task_scope = tuple(task.allowed_paths)
        protected_scope = tuple(task.protected_paths)
        deliverables = tuple(task.deliverables or task.allowed_paths)
        evidence_requirements = tuple(item.name or " ".join(item.command) for item in task.required_checks)
    merged_policy = read_json(orchestrator.run_dir / "prompt-compilation.json")["mergedPolicy"]
    ir = compile_ir(
        request_id=str(orchestrator.run_dir.name),
        role=role,
        goal=orchestrator.request,
        templates=[TemplatePolicy.from_dict(merged_policy)],
        contract_id=canonical_sha256(orchestrator.execution_brief),
        blueprint_id=canonical_sha256(view),
        prompt_id=invocation_seed,
        stop_when=stop_when,
        deliverables=deliverables,
        evidence_requirements=evidence_requirements,
        allowed_scope=task_scope,
        protected_scope=protected_scope,
        must_do=tuple(must_do),
        must_not=tuple(must_not),
        context_refs=tuple(context_refs),
        output_contract=output_contract,
        escalate_when=tuple(escalate_when),
    )
    return ir
