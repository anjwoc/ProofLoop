from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def canonical_role(value: str) -> str:
    lowered = value.lower()
    if "implementer-recovery" in lowered or "implementer_recovery" in lowered:
        return "implementer_recovery"
    if "implementer-fast" in lowered or "implementer_fast" in lowered:
        return "implementer_fast"
    if "planner" in lowered:
        return "planner_deep"
    if "reviewer" in lowered:
        return "reviewer_deep"
    return value


def summarize_trace(path: str | Path, required_roles: list[str] | None = None) -> dict[str, Any]:
    source = Path(path)
    events: list[dict[str, Any]] = []
    if source.exists():
        for line in source.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
    required = required_roles or ["planner_deep", "implementer_fast", "reviewer_deep"]
    by_role: dict[str, list[str]] = {}
    requested_by_role: dict[str, list[str]] = {}
    weak_evidence_roles: list[str] = []
    strong_evidence = {"HOST_RESOLVED", "HOST_ACTIVE_MODEL", "HOST_OUTPUT", "ACP_SESSION_CONFIG"}
    for event in events:
        raw_role = event.get("role")
        role = canonical_role(raw_role) if isinstance(raw_role, str) else None
        requested = event.get("requestedModel") or event.get("expectedModel")
        if role and isinstance(requested, str) and requested:
            requested_by_role.setdefault(role, []).append(requested)
        observed = event.get("observedModel")
        evidence = event.get("modelEvidence", "HOST_RESOLVED")
        if role and isinstance(observed, str) and observed:
            if evidence in strong_evidence:
                by_role.setdefault(role, []).append(observed)
            else:
                weak_evidence_roles.append(role)
    missing = [role for role in required if not by_role.get(role)]
    all_models = {model for models in by_role.values() for model in models}
    configured_models = {model for models in requested_by_role.values() for model in models}
    return {
        "schemaVersion": "2.0",
        "routingClaimed": len(required) > 1,
        "routingConfigured": len(configured_models) >= 2,
        "routingObserved": not missing and len(all_models) >= 2,
        "requiredRoles": required,
        "observedModelsByRole": by_role,
        "requestedModelsByRole": requested_by_role,
        "weakEvidenceRoles": sorted(set(weak_evidence_roles)),
        "missingRoles": missing,
        "eventCount": len(events),
    }
