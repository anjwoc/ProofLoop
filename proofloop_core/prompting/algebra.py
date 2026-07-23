from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Iterable

from proofloop_core.prompting.prompt_ir import PromptIR, PromptMetadata

COMPILER_VERSION = "algebra.v2"


class PromptTemplateConflict(ValueError):
    """Raised when selected templates cannot be merged without widening authority."""


class AuthorityLevel(IntEnum):
    READ_ONLY = 0
    REPOSITORY_MUTATION = 1
    EXPLICIT_ONLY = 2
    GIT_REMOTE = 3


@dataclass(frozen=True)
class TemplatePolicy:
    id: str
    version: str = "1.0"
    authority_ceiling: AuthorityLevel | None = None
    must_do: frozenset[str] = field(default_factory=frozenset)
    must_not: frozenset[str] = field(default_factory=frozenset)
    allowed_scope: frozenset[str] = field(default_factory=frozenset)
    protected_scope: frozenset[str] = field(default_factory=frozenset)
    proof_requirements: frozenset[str] = field(default_factory=frozenset)
    output_sections: tuple[str, ...] = field(default_factory=tuple)
    stop_conditions: frozenset[str] = field(default_factory=frozenset)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "authorityCeiling": self.authority_ceiling.name if self.authority_ceiling is not None else None,
            "mustDo": sorted(self.must_do),
            "mustNot": sorted(self.must_not),
            "allowedScope": sorted(self.allowed_scope),
            "protectedScope": sorted(self.protected_scope),
            "proofRequirements": sorted(self.proof_requirements),
            "outputSections": list(self.output_sections),
            "stopConditions": sorted(self.stop_conditions),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TemplatePolicy":
        ceiling = value.get("authorityCeiling")
        return cls(
            id=str(value["id"]),
            version=str(value.get("version") or "1.0"),
            authority_ceiling=AuthorityLevel[str(ceiling)] if ceiling else None,
            must_do=frozenset(str(item) for item in value.get("mustDo", [])),
            must_not=frozenset(str(item) for item in value.get("mustNot", [])),
            allowed_scope=frozenset(str(item) for item in value.get("allowedScope", [])),
            protected_scope=frozenset(str(item) for item in value.get("protectedScope", [])),
            proof_requirements=frozenset(str(item) for item in value.get("proofRequirements", [])),
            output_sections=tuple(str(item) for item in value.get("outputSections", [])),
            stop_conditions=frozenset(str(item) for item in value.get("stopConditions", [])),
        )


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized(values: Iterable[str]) -> dict[str, str]:
    return {" ".join(value.lower().split()): value for value in values}


def merge_templates(templates: list[TemplatePolicy]) -> TemplatePolicy:
    """Merge existing templates conservatively and reject contradictory authority.

    Union is safe for obligations and prohibitions. Allowed scope is an
    intersection across every non-empty declaration; a merge may narrow scope
    but can never widen it. Empty allowed scope means "not constrained by this
    template", not "allow everything".
    """

    if not templates:
        raise ValueError("Cannot merge empty template list")

    must_do = frozenset().union(*(template.must_do for template in templates))
    must_not = frozenset().union(*(template.must_not for template in templates))
    do_norm = _normalized(must_do)
    not_norm = _normalized(must_not)
    overlap = sorted(set(do_norm).intersection(not_norm))
    if overlap:
        raise PromptTemplateConflict(f"PROMPT_TEMPLATE_CONFLICT: contradictory rules {overlap}")

    non_empty_scopes = [set(template.allowed_scope) for template in templates if template.allowed_scope]
    if non_empty_scopes:
        allowed_scope = frozenset(set.intersection(*non_empty_scopes))
        if not allowed_scope:
            raise PromptTemplateConflict("PROMPT_SCOPE_WIDENING_REJECTED: selected scopes have no common path")
    else:
        allowed_scope = frozenset()

    ceilings = [template.authority_ceiling for template in templates if template.authority_ceiling is not None]
    merged_authority = min(ceilings) if ceilings else None

    sections: list[str] = []
    seen_sections: set[str] = set()
    for template in templates:
        for section in template.output_sections:
            if section not in seen_sections:
                seen_sections.add(section)
                sections.append(section)

    template_identity = [
        {"id": template.id, "version": template.version}
        for template in templates
    ]
    merged_id = f"merged.{_canonical_sha256(template_identity)[:16]}"
    return TemplatePolicy(
        id=merged_id,
        version="2.0",
        authority_ceiling=merged_authority,
        must_do=must_do,
        must_not=must_not,
        allowed_scope=allowed_scope,
        protected_scope=frozenset().union(*(template.protected_scope for template in templates)),
        proof_requirements=frozenset().union(*(template.proof_requirements for template in templates)),
        output_sections=tuple(sections),
        stop_conditions=frozenset().union(*(template.stop_conditions for template in templates)),
    )


INTENT_AUDIT = TemplatePolicy(
    id="intent.audit.v1",
    authority_ceiling=AuthorityLevel.READ_ONLY,
    must_do=frozenset((
        "Separate confirmed findings from hypotheses.",
        "Cite evidence for every material conclusion.",
    )),
    must_not=frozenset((
        "Modify repository files.",
        "Treat model claims as evidence.",
    )),
    proof_requirements=frozenset(("finding_provenance", "scope_coverage")),
    output_sections=("executive_summary", "findings", "evidence", "unresolved"),
    stop_conditions=frozenset(("Every material finding has evidence.",)),
)

INTENT_MUTATE = TemplatePolicy(
    id="intent.mutate.v1",
    authority_ceiling=AuthorityLevel.REPOSITORY_MUTATION,
    must_do=frozenset((
        "Inspect the existing implementation before editing.",
        "Restrict changes to allowed paths.",
    )),
    must_not=frozenset((
        "Push, merge, deploy, or perform external writes without explicit authority.",
        "Modify protected paths.",
    )),
    proof_requirements=frozenset(("baseline", "automated_verification", "scope_check")),
    output_sections=("result", "changed_files", "checks_executed", "evidence"),
    stop_conditions=frozenset(("Required behavior is implemented.", "Scope integrity passes.")),
)

OP_CLEANUP = TemplatePolicy(
    id="operation.cleanup.v1",
    must_do=frozenset(("Usage or reachability audit must precede deletion.",)),
    must_not=frozenset(("Delete solely because static search found no imports.",)),
    proof_requirements=frozenset(("no_reachable_runtime_path", "no_dynamic_registration")),
)

SURFACE_REPOSITORY = TemplatePolicy(
    id="surface.repository.v1",
    must_do=frozenset(("Ground in repository_instructions and manifests.",)),
    proof_requirements=frozenset(("paths", "symbols", "diff")),
)

RISK_T2 = TemplatePolicy(
    id="risk.t2",
    must_do=frozenset(("Planner required.", "Independent review required.")),
    proof_requirements=frozenset(("baseline", "automated_checks", "scope_integrity", "independent_review")),
)


def compile_ir(
    request_id: str,
    role: str,
    goal: str,
    templates: list[TemplatePolicy],
    *,
    contract_id: str | None = None,
    blueprint_id: str | None = None,
    prompt_id: str | None = None,
    stop_when: str = "",
    deliverables: tuple[str, ...] = (),
    evidence_requirements: tuple[str, ...] = (),
    allowed_scope: tuple[str, ...] = (),
    protected_scope: tuple[str, ...] = (),
    must_do: tuple[str, ...] = (),
    must_not: tuple[str, ...] = (),
    context_refs: tuple[str, ...] = (),
    allowed_tools: tuple[str, ...] = (),
    output_contract: str = "Standard JSON Result",
    escalate_when: tuple[str, ...] = ("Authority Ceiling Exceeded",),
) -> PromptIR:
    """Compile a content-addressed PromptIR from the selected existing templates."""

    merged = merge_templates(templates)
    combined_must_do = tuple(dict.fromkeys((*sorted(merged.must_do), *must_do)))
    combined_must_not = tuple(dict.fromkeys((*sorted(merged.must_not), *must_not)))
    do_norm = _normalized(combined_must_do)
    not_norm = _normalized(combined_must_not)
    if set(do_norm).intersection(not_norm):
        raise PromptTemplateConflict("PROMPT_TEMPLATE_CONFLICT: invocation rules contradict template rules")

    effective_allowed = tuple(allowed_scope or sorted(merged.allowed_scope))
    if merged.allowed_scope and allowed_scope:
        if not set(allowed_scope).issubset(merged.allowed_scope):
            raise PromptTemplateConflict("PROMPT_SCOPE_WIDENING_REJECTED: invocation widened template scope")
    effective_protected = tuple(dict.fromkeys((*sorted(merged.protected_scope), *protected_scope)))
    effective_evidence = tuple(dict.fromkeys((*sorted(merged.proof_requirements), *evidence_requirements)))
    effective_deliverables = tuple(deliverables or merged.output_sections)
    effective_stop = stop_when or "\n- ".join(("", *sorted(merged.stop_conditions)))

    identity = {
        "requestId": request_id,
        "role": role,
        "goal": goal,
        "contractId": contract_id,
        "blueprintId": blueprint_id,
        "template": merged.to_dict(),
        "deliverables": effective_deliverables,
        "evidence": effective_evidence,
        "allowedScope": effective_allowed,
        "protectedScope": effective_protected,
        "mustDo": combined_must_do,
        "mustNot": combined_must_not,
        "contextRefs": context_refs,
        "outputContract": output_contract,
    }
    digest = _canonical_sha256(identity)
    return PromptIR(
        prompt_id=prompt_id or f"prompt-{digest[:24]}",
        request_id=request_id,
        contract_id=contract_id or f"contract-{digest[:24]}",
        blueprint_id=blueprint_id or merged.id,
        role=role,
        goal=goal,
        stop_when=effective_stop,
        deliverables=effective_deliverables,
        evidence_requirements=effective_evidence,
        allowed_scope=effective_allowed,
        protected_scope=effective_protected,
        must_do=combined_must_do,
        must_not=combined_must_not,
        context_refs=context_refs,
        allowed_tools=allowed_tools,
        output_contract=output_contract,
        escalate_when=escalate_when,
        metadata=PromptMetadata(
            compiler_version=COMPILER_VERSION,
            generation_time="content-addressed",
            content_sha256=digest,
        ),
    )
