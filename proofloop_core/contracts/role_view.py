from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from proofloop_core.contracts.execution_brief import canonical_sha256, validate_execution_brief

SCHEMA_VERSION = "1.0"

_ROLE_FIELDS: dict[str, set[str]] = {
    "explorer": {"objective", "facts", "inferences", "openQuestions", "scope"},
    "planner_deep": {"objective", "acceptanceCriteria", "constraints", "nonGoals", "scope", "openQuestions", "riskSignals"},
    "implementer_fast": {"objective", "acceptanceCriteria", "constraints", "nonGoals", "scope"},
    "recovery": {"objective", "acceptanceCriteria", "constraints", "nonGoals", "scope", "riskSignals", "unknowns"},
    "reviewer": {"objective", "acceptanceCriteria", "constraints", "nonGoals", "scope", "assumptions", "openQuestions", "riskSignals", "unknowns"},
}

KNOWN_ROLES = frozenset(_ROLE_FIELDS)
_ROLE_ALIASES = {
    "explorer_fast": "explorer",
    "implementer_recovery": "recovery",
    "reviewer_deep": "reviewer",
}
_AUTHORITY_REFS = {
    "originalRequest": "request-envelope.json",
    "intentContract": "intent-contract.json",
    "promptCompilation": "prompt-compilation.json",
    "executionBrief": "execution-brief.json",
    "proofGraph": "proof-graph.json",
}


class RoleViewValidationError(ValueError):
    """Raised when role-view projection inputs are invalid."""


def project_role_view(
    brief: Mapping[str, Any],
    role: str,
    invocation_id: str,
    *,
    proof_graph_sha256: str | None = None,
    obligation_revision: int = 0,
) -> dict[str, Any]:
    """Project a minimal role view from a validated brief.

    Shadow briefs may be projected for deterministic inspection, but are
    non-executable and reveal candidates only. The mandatory execution path
    calls this with an active brief through ``compile_role_ir``.
    """

    resolved_role = _ROLE_ALIASES.get(role, role)
    if resolved_role not in _ROLE_FIELDS:
        raise RoleViewValidationError(f"unknown role: {role}")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise RoleViewValidationError("invocation_id must be a non-empty string")

    validate_execution_brief(brief)
    active = brief.get("kind") == "EXECUTION_BRIEF"
    brief_sha = canonical_sha256(dict(brief))
    view: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "role": role,
        "invocationId": invocation_id,
        "provenance": {
            "executionBriefSha256": brief_sha,
            "proofGraphSha256": proof_graph_sha256,
            "obligationRevision": obligation_revision,
        },
        "authorityRefs": dict(_AUTHORITY_REFS),
    }
    for field in sorted(_ROLE_FIELDS[resolved_role]):
        value = brief.get(field)
        if value is not None:
            view[field] = copy.deepcopy(value)

    if "scope" in view and isinstance(view["scope"], dict):
        scope = view["scope"]
        if active:
            view["scope"] = {
                "candidates": list(scope.get("candidates", [])),
                "approvedPaths": list(scope.get("approvedPaths", [])),
                "protectedPaths": list(scope.get("protectedPaths", [])),
                "status": scope.get("status"),
            }
        else:
            view["scope"] = {"candidates": list(scope.get("candidates", []))}

    if active:
        view["projectionSha256"] = canonical_sha256(view)
    return view
