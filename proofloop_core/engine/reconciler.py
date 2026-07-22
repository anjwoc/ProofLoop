from __future__ import annotations

import copy
from typing import Any


class ReconcilerError(ValueError):
    """Raised when a proposal violates the reconciliation contract."""


def reconcile_proposal(shadow_brief: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    """Reconcile a refinement proposal against the shadow brief.
    
    ponytail: the simplest check that blocks inventing facts, criteria, and dropping questions.
    """
    if proposal.get("schemaVersion") != shadow_brief.get("schemaVersion"):
        raise ReconcilerError("schema version mismatch")

    # 1. Acceptance obligations are immutable. A refinement cannot quietly
    # drop a difficult criterion any more than it can invent a new one.
    shadow_ac_ids = {ac["id"] for ac in shadow_brief.get("acceptanceCriteria", [])}
    prop_ac_ids = {ac["id"] for ac in proposal.get("acceptanceCriteria", [])}
    if not prop_ac_ids.issubset(shadow_ac_ids):
        invented = sorted(prop_ac_ids - shadow_ac_ids)
        raise ReconcilerError(f"invented criteria rejected: {invented}")
    if prop_ac_ids != shadow_ac_ids:
        raise ReconcilerError("dropped acceptance criterion")

    # 2. Reject invented facts
    shadow_fact_ids = {f["id"] for f in shadow_brief.get("facts", [])}
    prop_fact_ids = {f["id"] for f in proposal.get("facts", [])}
    if not prop_fact_ids.issubset(shadow_fact_ids):
        invented = sorted(prop_fact_ids - shadow_fact_ids)
        raise ReconcilerError(f"invented facts rejected: {invented}")
    if prop_fact_ids != shadow_fact_ids:
        raise ReconcilerError("dropped fact")

    # 3. Open questions union and no blocking downgrade
    shadow_questions = {q["id"]: q.get("blocking", True) for q in shadow_brief.get("openQuestions", [])}
    prop_questions = {q["id"]: q.get("blocking", True) for q in proposal.get("openQuestions", [])}
    
    for qid, blocking in shadow_questions.items():
        if qid not in prop_questions:
            raise ReconcilerError(f"dropped open question: {qid}")
        if blocking and not prop_questions[qid]:
            raise ReconcilerError(f"downgraded blocking question: {qid}")

    # 4. Unknowns cannot be hidden
    shadow_unknowns = {u["statement"] if isinstance(u, dict) else u for u in shadow_brief.get("unknowns", [])}
    prop_unknowns = {u["statement"] if isinstance(u, dict) else u for u in proposal.get("unknowns", [])}
    if not shadow_unknowns.issubset(prop_unknowns):
        dropped = sorted(shadow_unknowns - prop_unknowns)
        raise ReconcilerError(f"dropped unknowns: {dropped}")
    if prop_unknowns != shadow_unknowns:
        raise ReconcilerError("invented unknowns require a new shadow brief")

    # 5. Authorization boundary cannot be widened (exact string check for lazy simplicity)
    if proposal.get("authorizationBoundary") != shadow_brief.get("authorizationBoundary"):
        raise ReconcilerError("authorization boundary changed")

    # 6. Scope can only be constrained from user-declared candidates. It may
    # never introduce a new path or discard candidate visibility.
    shadow_scope = shadow_brief.get("scope")
    proposal_scope = proposal.get("scope")
    if isinstance(shadow_scope, dict) or isinstance(proposal_scope, dict):
        if not isinstance(shadow_scope, dict) or not isinstance(proposal_scope, dict):
            raise ReconcilerError("scope shape changed")
        shadow_candidates = set(shadow_scope.get("candidates", []))
        proposal_candidates = set(proposal_scope.get("candidates", []))
        if proposal_candidates != shadow_candidates:
            raise ReconcilerError("scope candidates changed")
        approved = set(proposal_scope.get("approvedPaths", []))
        protected = set(proposal_scope.get("protectedPaths", []))
        if not approved.issubset(shadow_candidates) or not protected.issubset(shadow_candidates):
            raise ReconcilerError("scope path outside candidates")
        if approved.intersection(protected):
            raise ReconcilerError("scope path both approved and protected")

    shadow_kind = shadow_brief.get("kind")
    proposal_kind = proposal.get("kind")
    if shadow_kind and proposal_kind not in {shadow_kind, "EXECUTION_BRIEF"}:
        raise ReconcilerError("invalid execution brief kind transition")

    # Return only a validated proposal. The caller re-hashes and validates the
    # complete execution-brief schema before projecting it to roles.
    return proposal


def build_conservative_proposal(shadow_brief: dict[str, Any]) -> dict[str, Any]:
    """Create the smallest non-identity active brief from immutable shadow data.

    This is deliberately Core-owned rather than model-authored: it changes the
    lifecycle kind and marks only explicit target candidates as approved. It
    does not invent facts, criteria, checks, or open-question resolutions.
    """
    proposal = copy.deepcopy(shadow_brief)
    proposal["kind"] = "EXECUTION_BRIEF"
    scope = dict(proposal.get("scope") or {})
    candidates = list(scope.get("candidates") or [])
    proposal["scope"] = {
        "candidates": list(candidates),
        "approvedPaths": list(candidates),
        "protectedPaths": [],
        "status": "CONSTRAINED",
    }
    return proposal
