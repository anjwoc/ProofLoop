from __future__ import annotations

from pathlib import Path
from typing import Any

from .assurance import build_assurance_report
from .io import read_json


VALID_STATES = {"PROVEN", "UNPROVEN", "FAILED", "BLOCKED"}


def _load_optional(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json(path)


def build_truth_report(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir)
    checks = _load_optional(root / "checks" / "checks.json")
    diff = _load_optional(root / "diff-guard.json")
    review = _load_optional(root / "review.json")
    trace = _load_optional(root / "model-trace-summary.json")
    intent = _load_optional(root / "intent-contract.json")
    proof_graph = _load_optional(root / "proof-graph.json")
    assurance = build_assurance_report(root)

    blockers: list[str] = []
    unproven: list[str] = []
    if not checks:
        blockers.append("CHECK_EVIDENCE_MISSING")
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
    if intent is not None:
        if not proof_graph:
            blockers.append("PROOF_GRAPH_MISSING")
        else:
            open_obligations = [
                str(item.get("id"))
                for item in proof_graph.get("obligations", [])
                if isinstance(item, dict) and item.get("status") != "CLOSED"
            ]
            blockers.extend(f"PROOF_OBLIGATIONS_OPEN:{item}" for item in open_obligations)

    blockers.extend(assurance.get("blocking", []))
    unproven.extend(assurance.get("unproven", []))

    if blockers:
        verdict = "FAILED"
    elif unproven:
        verdict = "UNPROVEN"
    else:
        verdict = "PROVEN"
    return {
        "schemaVersion": "2.0",
        "verdict": verdict,
        "blockers": blockers,
        "unproven": unproven,
        "assurance": assurance,
        "evidence": {
            "checks": str(root / "checks" / "checks.json") if checks else None,
            "diffGuard": str(root / "diff-guard.json") if diff else None,
            "review": str(root / "review.json") if review else None,
            "modelTrace": str(root / "model-trace-summary.json") if trace else None,
            "proofGraph": str(root / "proof-graph.json") if proof_graph else None,
            "claims": str(root / "claims.json") if (root / "claims.json").exists() else None,
            "assurance": str(root / "assurance-report.json"),
        },
    }
