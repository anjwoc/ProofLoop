from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from proofloop_core.execution_brief import canonical_sha256, validate_execution_brief

SCHEMA_VERSION = "1.0"

# ponytail: table-driven field selection, one dict lookup instead of five classes
_ROLE_FIELDS: dict[str, set[str]] = {
    "explorer": {"objective", "facts", "openQuestions"},
    "planner_deep": {"objective", "acceptanceCriteria", "constraints", "nonGoals", "scope", "openQuestions", "riskSignals"},
    "implementer_fast": {"objective", "acceptanceCriteria", "constraints", "scope"},
    "recovery": {"objective", "acceptanceCriteria", "constraints", "scope", "riskSignals", "unknowns"},
    "reviewer": {"objective", "acceptanceCriteria", "scope", "assumptions", "openQuestions", "riskSignals", "unknowns"},
}

KNOWN_ROLES = frozenset(_ROLE_FIELDS)

# The orchestrator/host_runner use canonical role identifiers; map them onto the
# internal short field-set keys so both vocabularies project identically.
_ROLE_ALIASES = {
    "explorer_fast": "explorer",
    "implementer_recovery": "recovery",
    "reviewer_deep": "reviewer",
}

_AUTHORITY_REFS = {
    "originalRequest": "request.json",
    "executionBrief": "execution-brief.json",
    "proofGraph": "proof-graph.json",
}


class RoleViewValidationError(ValueError):
    """Raised when role view projection inputs are invalid."""


def project_role_view(
    brief: Mapping[str, Any],
    role: str,
    invocation_id: str,
    *,
    proof_graph_sha256: str | None = None,
    obligation_revision: int = 0,
) -> dict[str, Any]:
    """Project a minimal role view from an execution brief.

    Returns an invocation-scoped envelope containing only the fields
    the role needs. Does not mutate the input brief.
    """
    resolved_role = _ROLE_ALIASES.get(role, role)
    if resolved_role not in _ROLE_FIELDS:
        raise RoleViewValidationError(f"unknown role: {role}")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise RoleViewValidationError("invocation_id must be a non-empty string")

    validate_execution_brief(brief)

    brief_sha = canonical_sha256(dict(brief))
    fields = _ROLE_FIELDS[resolved_role]

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

    for field in sorted(fields):
        value = brief.get(field)
        if value is not None:
            view[field] = copy.deepcopy(value)

    # ponytail: scope in role view only shows candidates, never approvedPaths (shadow brief)
    if "scope" in view and isinstance(view["scope"], dict):
        view["scope"] = {"candidates": view["scope"].get("candidates", [])}

    return view
