from __future__ import annotations

from pathlib import Path
from typing import Any

from proofloop_core.assurance.assurance import build_assurance_report
from proofloop_core.assurance.live_evidence import validate_core_evidence
from proofloop_core.context.io import read_json
from proofloop_core.contracts.evidence_policy import ClaimType

VALID_STATES = {"PROVEN", "PARTIAL", "UNPROVEN", "FAILED", "BLOCKED"}
_SEMANTIC_CLAIMS = {ClaimType.INTENT_ALIGNMENT.value, ClaimType.SIMPLICITY.value}


def _load_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    value = read_json(path)
    return value if isinstance(value, dict) else None


def _claim_scope(claims: dict[str, str]) -> str:
    if claims.get(ClaimType.HOST_EXECUTION.value) == "CLOSED":
        return "AUTHENTICATED_HOST"
    local = (
        ClaimType.PROMPT_CONTRACT_APPLIED.value,
        ClaimType.PRODUCT_BEHAVIOR.value,
        ClaimType.SCOPE_INTEGRITY.value,
    )
    if all(claims.get(item) in {"CLOSED", "NOT_REQUIRED"} for item in local):
        return "LOCAL_DETERMINISTIC"
    return "UNPROVEN"


def build_truth_report(run_dir: str | Path, *, require_core_evidence: bool = False) -> dict[str, Any]:
    root = Path(run_dir)
    run = _load_optional(root / "run.json") or {}
    provenance = _load_optional(root / "run-provenance.json") or {}
    prompt_compilation = _load_optional(root / "prompt-compilation.json")
    checks = _load_optional(root / "checks" / "checks.json")
    diff = _load_optional(root / "diff-guard.json")
    review = _load_optional(root / "review.json")
    trace = _load_optional(root / "model-trace-summary.json")
    intent = _load_optional(root / "intent-contract.json")
    proof_graph = _load_optional(root / "proof-graph.json")
    assurance = build_assurance_report(root)
    live_evidence: dict[str, Any] | None = None
    if require_core_evidence or (root / "live-evidence.json").exists():
        live_evidence = validate_core_evidence(root)
        if live_evidence.get("status") == "VALID":
            checks = live_evidence.get("checks") if isinstance(live_evidence.get("checks"), dict) else checks
            diff = live_evidence.get("diff") if isinstance(live_evidence.get("diff"), dict) else diff

    blockers: list[str] = []
    unproven: list[str] = []
    if live_evidence is not None and live_evidence.get("status") != "VALID":
        reasons = live_evidence.get("reasons")
        if isinstance(reasons, list) and reasons:
            blockers.extend(f"LIVE_EVIDENCE_INVALID:{reason}" for reason in reasons)
        else:
            blockers.append("LIVE_EVIDENCE_INVALID")

    if intent is not None and not prompt_compilation:
        blockers.append("PROMPT_CONTRACT_MISSING")
    if not checks:
        blockers.append("CHECK_EVIDENCE_MISSING")
    else:
        check_items = checks.get("checks")
        if not isinstance(check_items, list) or not check_items:
            blockers.append("CHECK_EVIDENCE_EMPTY")
        elif checks.get("verdict") != "PASS":
            blockers.append("CHECKS_FAILED")
    if not diff:
        blockers.append("DIFF_GUARD_MISSING")
    elif diff.get("verdict") != "PASS":
        blockers.append("DIFF_GUARD_FAILED")

    if not review:
        unproven.append("REVIEW_EVIDENCE_MISSING")
    elif review.get("verdict") != "APPROVED":
        blockers.append("REVIEW_NOT_APPROVED")
    if not trace:
        unproven.append("MODEL_TRACE_MISSING")
    elif trace.get("routingClaimed") and not trace.get("routingObserved"):
        unproven.append("MODEL_ROUTING_UNPROVEN")

    claims: dict[str, str] = {claim.value: "NOT_REQUIRED" for claim in ClaimType}
    if intent is not None:
        if not proof_graph:
            blockers.append("PROOF_GRAPH_MISSING")
        else:
            raw_claims = proof_graph.get("claims")
            if isinstance(raw_claims, dict):
                for key, status in raw_claims.items():
                    if key in claims and status in {"OPEN", "CLOSED", "NOT_REQUIRED"}:
                        claims[key] = status
            for item in proof_graph.get("obligations", []):
                if not isinstance(item, dict) or not item.get("required", True) or item.get("status") == "CLOSED":
                    continue
                obligation_id = str(item.get("id"))
                claim_type = str(item.get("claimType") or ClaimType.PRODUCT_BEHAVIOR.value)
                if claim_type in _SEMANTIC_CLAIMS:
                    unproven.append(f"PROOF_OBLIGATION_UNPROVEN:{obligation_id}")
                else:
                    blockers.append(f"PROOF_OBLIGATIONS_OPEN:{obligation_id}")

    blockers.extend(assurance.get("blocking", []))
    unproven.extend(assurance.get("unproven", []))
    blockers = list(dict.fromkeys(blockers))
    unproven = list(dict.fromkeys(item for item in unproven if item not in blockers))

    if blockers:
        verdict = "FAILED"
    elif unproven:
        verdict = "PARTIAL"
    else:
        verdict = "PROVEN"
    scope = _claim_scope(claims)
    return {
        "schemaVersion": "3.0",
        "verdict": verdict,
        "claimScope": scope,
        "claims": claims,
        "blockers": blockers,
        "unproven": unproven,
        "evidenceOrigin": provenance.get("invocationKind", "UNKNOWN"),
        "host": provenance.get("requestedHost") or run.get("hostRequested") or "unresolved",
        "assurance": assurance,
        "evidence": {
            "promptCompilation": str(root / "prompt-compilation.json") if prompt_compilation else None,
            "checks": str(root / "checks" / "checks.json") if checks else None,
            "diffGuard": str(root / "diff-guard.json") if diff else None,
            "review": str(root / "review.json") if review else None,
            "modelTrace": str(root / "model-trace-summary.json") if trace else None,
            "proofGraph": str(root / "proof-graph.json") if proof_graph else None,
            "claims": str(root / "claims.json") if (root / "claims.json").exists() else None,
            "assurance": str(root / "assurance-report.json"),
            "liveEvidence": str(root / "live-evidence.json") if live_evidence is not None else None,
            "runProvenance": str(root / "run-provenance.json") if provenance else None,
            "runPolicy": str(root / "run-policy.json") if (root / "run-policy.json").exists() else None,
        },
    }
