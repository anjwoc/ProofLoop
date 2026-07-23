from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum

from proofloop_core.prompting.prompt_ir import PromptIR, PromptMetadata


class AuthorityLevel(IntEnum):
    READ_ONLY = 0
    REPOSITORY_MUTATION = 1
    EXPLICIT_ONLY = 2
    GIT_REMOTE = 3


@dataclass(frozen=True)
class TemplatePolicy:
    id: str
    authority_ceiling: AuthorityLevel | None = None
    must_do: frozenset[str] = field(default_factory=frozenset)
    must_not: frozenset[str] = field(default_factory=frozenset)
    allowed_scope: frozenset[str] = field(default_factory=frozenset)
    protected_scope: frozenset[str] = field(default_factory=frozenset)
    proof_requirements: frozenset[str] = field(default_factory=frozenset)
    output_sections: tuple[str, ...] = field(default_factory=tuple)
    stop_conditions: frozenset[str] = field(default_factory=frozenset)


def merge_templates(templates: list[TemplatePolicy]) -> TemplatePolicy:
    """
    Merges multiple TemplatePolicies following strict algebra rules:
    - Must_do, Must_not, Protected Scope, Proof Requirements, Stop Conditions -> UNION
    - Allowed Scope -> INTERSECTION (or union if one is empty depending on strictness, we'll use union for simplicity in MVP unless bounded)
    - Authority Ceiling -> MIN (most restrictive)
    - Output Sections -> ORDERED UNION (deduplicated)
    """
    if not templates:
        raise ValueError("Cannot merge empty template list")

    merged_authority = AuthorityLevel.GIT_REMOTE
    for t in templates:
        if t.authority_ceiling is not None:
            merged_authority = min(merged_authority, t.authority_ceiling)

    # Ordered Union for sections
    sections = []
    seen_sections = set()
    for t in templates:
        for sec in t.output_sections:
            if sec not in seen_sections:
                seen_sections.add(sec)
                sections.append(sec)

    return TemplatePolicy(
        id="merged.policy",
        authority_ceiling=merged_authority,
        must_do=frozenset().union(*(t.must_do for t in templates)),
        must_not=frozenset().union(*(t.must_not for t in templates)),
        allowed_scope=frozenset().union(*(t.allowed_scope for t in templates)),
        protected_scope=frozenset().union(*(t.protected_scope for t in templates)),
        proof_requirements=frozenset().union(*(t.proof_requirements for t in templates)),
        output_sections=tuple(sections),
        stop_conditions=frozenset().union(*(t.stop_conditions for t in templates)),
    )


# --- HARDCODED TEMPLATES (Ponytail V1) ---

INTENT_AUDIT = TemplatePolicy(
    id="intent.audit.v1",
    authority_ceiling=AuthorityLevel.READ_ONLY,
    must_do=frozenset(["Separate confirmed findings from hypotheses.", "Cite evidence for every material conclusion."]),
    must_not=frozenset(["Modify repository files.", "Treat model claims as evidence."]),
    proof_requirements=frozenset(["finding_provenance", "scope_coverage"]),
    output_sections=("executive_summary", "findings", "evidence", "unresolved"),
    stop_conditions=frozenset(["Every material finding has evidence."]),
)

INTENT_MUTATE = TemplatePolicy(
    id="intent.mutate.v1",
    authority_ceiling=AuthorityLevel.REPOSITORY_MUTATION,
    must_do=frozenset(["Inspect the existing implementation before editing.", "Restrict changes to allowed paths."]),
    must_not=frozenset(["Push, merge, deploy, or perform external writes without explicit authority.", "Modify protected paths."]),
    proof_requirements=frozenset(["baseline", "automated_verification", "scope_check"]),
    output_sections=("result", "changed_files", "checks_executed", "evidence"),
    stop_conditions=frozenset(["Required behavior is implemented.", "Scope integrity passes."]),
)

OP_CLEANUP = TemplatePolicy(
    id="operation.cleanup.v1",
    must_do=frozenset(["Usage or reachability audit must precede deletion."]),
    must_not=frozenset(["Delete solely because static search found no imports."]),
    proof_requirements=frozenset(["no_reachable_runtime_path", "no_dynamic_registration"]),
)

SURFACE_REPOSITORY = TemplatePolicy(
    id="surface.repository.v1",
    must_do=frozenset(["Ground in repository_instructions and manifests."]),
    proof_requirements=frozenset(["paths", "symbols", "diff"]),
)

RISK_T2 = TemplatePolicy(
    id="risk.t2",
    must_do=frozenset(["Planner required.", "Independent review required."]),
    proof_requirements=frozenset(["baseline", "automated_checks", "scope_integrity", "independent_review"]),
)


def compile_ir(
    request_id: str,
    role: str,
    goal: str,
    templates: list[TemplatePolicy]
) -> PromptIR:
    """
    Takes a list of TemplatePolicy, merges them algebraically, and maps to the existing PromptIR schema.
    """
    merged = merge_templates(templates)

    return PromptIR(
        prompt_id=f"prompt_{int(time.time())}",
        request_id=request_id,
        contract_id="contract_algebra_1",
        blueprint_id=merged.id,
        role=role,
        goal=goal,
        stop_when="\n- ".join([""] + list(merged.stop_conditions)),
        deliverables=merged.output_sections,
        evidence_requirements=tuple(merged.proof_requirements),
        allowed_scope=tuple(merged.allowed_scope),
        protected_scope=tuple(merged.protected_scope),
        must_do=tuple(merged.must_do),
        must_not=tuple(merged.must_not),
        context_refs=(),
        allowed_tools=(),
        output_contract="Standard JSON Result",
        escalate_when=("Authority Ceiling Exceeded",),
        metadata=PromptMetadata(compiler_version="algebra.v1", generation_time=str(int(time.time()))),
    )
