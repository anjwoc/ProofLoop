from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .io import read_json

_ALLOWED_KINDS = {"FACT", "INFERENCE", "UNKNOWN"}
_REQUIRED_CATEGORIES = {"CHECK_RESULT", "CHANGE_SCOPE", "REVIEW_RESULT", "SIMPLICITY"}


def _json_pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError("jsonPointer must be empty or start with '/'")
    current = value
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, dict):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        else:
            raise KeyError(token)
    return current


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_artifact(root: Path, relative: str) -> Path:
    if not relative or Path(relative).is_absolute():
        raise ValueError("artifact must be a non-empty run-relative path")
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError("artifact escapes run directory")
    return candidate


def _audit_evidence(root: Path, item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"status": "INVALID", "reason": "evidence must be an object"}
    relative = item.get("artifact")
    if not isinstance(relative, str):
        return {"status": "INVALID", "reason": "artifact is required"}
    try:
        path = _safe_artifact(root, relative)
    except ValueError as exc:
        return {"status": "INVALID", "artifact": relative, "reason": str(exc)}
    if not path.exists() or not path.is_file():
        return {"status": "MISSING", "artifact": relative}

    result: dict[str, Any] = {"status": "SUPPORTED", "artifact": relative}
    expected_hash = item.get("sha256")
    if expected_hash is not None:
        if not isinstance(expected_hash, str):
            return {"status": "INVALID", "artifact": relative, "reason": "sha256 must be a string"}
        observed_hash = _sha256(path)
        result["observedSha256"] = observed_hash
        if observed_hash != expected_hash:
            result["status"] = "CONTRADICTED"
            result["reason"] = "sha256 mismatch"
            return result

    pointer = item.get("jsonPointer")
    has_equals = "equals" in item
    if pointer is not None or has_equals:
        if not isinstance(pointer, str):
            return {"status": "INVALID", "artifact": relative, "reason": "jsonPointer is required for equals assertions"}
        try:
            document = read_json(path)
            observed = _json_pointer(document, pointer)
        except Exception as exc:
            return {"status": "MISSING", "artifact": relative, "jsonPointer": pointer, "reason": str(exc)}
        result["jsonPointer"] = pointer
        result["observed"] = observed
        if has_equals and observed != item.get("equals"):
            result["status"] = "CONTRADICTED"
            result["expected"] = item.get("equals")
    return result


def audit_claims(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    ledger_path = root / "claims.json"
    if not ledger_path.exists():
        return {
            "verdict": "UNPROVEN",
            "blocking": [],
            "unproven": ["CLAIM_LEDGER_MISSING"],
            "claims": [],
            "requiredCategories": sorted(_REQUIRED_CATEGORIES),
        }

    try:
        ledger = read_json(ledger_path)
    except Exception as exc:
        return {
            "verdict": "FAILED",
            "blocking": [f"CLAIM_LEDGER_INVALID:{exc}"],
            "unproven": [],
            "claims": [],
            "requiredCategories": sorted(_REQUIRED_CATEGORIES),
        }
    raw_claims = ledger.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        return {
            "verdict": "FAILED",
            "blocking": ["CLAIM_LEDGER_EMPTY"],
            "unproven": [],
            "claims": [],
            "requiredCategories": sorted(_REQUIRED_CATEGORIES),
        }

    audited: list[dict[str, Any]] = []
    blocking: list[str] = []
    unproven: list[str] = []
    supported_categories: set[str] = set()

    for index, claim in enumerate(raw_claims):
        if not isinstance(claim, dict):
            blocking.append(f"CLAIM_{index}_INVALID")
            continue
        claim_id = claim.get("id") if isinstance(claim.get("id"), str) else f"claim-{index + 1}"
        category = claim.get("category") if isinstance(claim.get("category"), str) else "UNSPECIFIED"
        kind = claim.get("kind")
        statement = claim.get("statement")
        evidence = claim.get("evidence") or []
        claim_result: dict[str, Any] = {
            "id": claim_id,
            "category": category,
            "kind": kind,
            "statement": statement,
            "status": "UNSUPPORTED",
            "evidence": [],
        }
        if kind not in _ALLOWED_KINDS or not isinstance(statement, str) or not statement.strip():
            claim_result["status"] = "INVALID"
            blocking.append(f"{claim_id}:INVALID_CLAIM")
            audited.append(claim_result)
            continue
        if kind == "UNKNOWN":
            claim_result["status"] = "ACKNOWLEDGED_UNKNOWN"
            unproven.append(f"{claim_id}:UNKNOWN")
            audited.append(claim_result)
            continue
        if not isinstance(evidence, list) or not evidence:
            claim_result["status"] = "UNSUPPORTED"
            unproven.append(f"{claim_id}:EVIDENCE_MISSING")
            audited.append(claim_result)
            continue
        evidence_results = [_audit_evidence(root, item) for item in evidence]
        claim_result["evidence"] = evidence_results
        statuses = {item["status"] for item in evidence_results}
        if "CONTRADICTED" in statuses:
            claim_result["status"] = "CONTRADICTED"
            blocking.append(f"{claim_id}:CONTRADICTED")
        elif statuses - {"SUPPORTED"}:
            claim_result["status"] = "UNSUPPORTED"
            unproven.append(f"{claim_id}:EVIDENCE_UNSUPPORTED")
        elif kind == "INFERENCE" and not isinstance(claim.get("reasoning"), str):
            claim_result["status"] = "UNSUPPORTED"
            unproven.append(f"{claim_id}:INFERENCE_REASONING_MISSING")
        else:
            claim_result["status"] = "SUPPORTED_INFERENCE" if kind == "INFERENCE" else "SUPPORTED"
            supported_categories.add(category)
        audited.append(claim_result)

    trace_path = root / "model-trace-summary.json"
    required_categories = set(_REQUIRED_CATEGORIES)
    if trace_path.exists():
        try:
            trace = read_json(trace_path)
            if trace.get("routingClaimed"):
                required_categories.add("MODEL_ROUTING")
        except Exception:
            pass
    for missing in sorted(required_categories - supported_categories):
        unproven.append(f"REQUIRED_CLAIM_CATEGORY_MISSING:{missing}")

    verdict = "FAILED" if blocking else "UNPROVEN" if unproven else "PROVEN"
    return {
        "verdict": verdict,
        "blocking": blocking,
        "unproven": unproven,
        "claims": audited,
        "requiredCategories": sorted(required_categories),
        "supportedCategories": sorted(supported_categories),
    }


def audit_simplicity(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    diff_path = root / "diff-guard.json"
    review_path = root / "review.json"
    blocking: list[str] = []
    unproven: list[str] = []
    evidence: dict[str, Any] = {}

    if not diff_path.exists():
        blocking.append("DIFF_GUARD_MISSING")
    else:
        diff = read_json(diff_path)
        evidence["metrics"] = diff.get("metrics")
        evidence["changeBudget"] = diff.get("changeBudget")
        evidence["simplicityPlan"] = diff.get("simplicityPlan")
        bloat_codes = {
            "CHANGED_FILE_BUDGET_EXCEEDED",
            "ADDED_LINE_BUDGET_EXCEEDED",
            "NEW_FILE_BUDGET_EXCEEDED",
            "DEPENDENCY_CHANGE_FORBIDDEN",
        }
        observed = {item.get("code") for item in diff.get("violations", []) if isinstance(item, dict)}
        if observed & bloat_codes:
            blocking.extend(sorted(observed & bloat_codes))

    if not review_path.exists():
        unproven.append("SIMPLICITY_REVIEW_MISSING")
    else:
        review = read_json(review_path)
        simplicity_verdict = review.get("simplicityVerdict")
        evidence["reviewVerdict"] = simplicity_verdict
        evidence["deletionCandidates"] = review.get("deletionCandidates", [])
        if simplicity_verdict == "OVERBUILT":
            blocking.append("REVIEW_FOUND_OVERBUILD")
        elif simplicity_verdict == "CANNOT_VERIFY":
            unproven.append("SIMPLICITY_CANNOT_VERIFY")
        elif simplicity_verdict != "MINIMAL":
            unproven.append("SIMPLICITY_VERDICT_MISSING")

    verdict = "FAILED" if blocking else "UNPROVEN" if unproven else "PROVEN"
    return {"verdict": verdict, "blocking": blocking, "unproven": unproven, "evidence": evidence}


def build_assurance_report(run_dir: str | Path) -> dict[str, Any]:
    claims = audit_claims(run_dir)
    simplicity = audit_simplicity(run_dir)
    blocking = [f"CLAIMS:{item}" for item in claims["blocking"]] + [f"SIMPLICITY:{item}" for item in simplicity["blocking"]]
    unproven = [f"CLAIMS:{item}" for item in claims["unproven"]] + [f"SIMPLICITY:{item}" for item in simplicity["unproven"]]
    verdict = "FAILED" if blocking else "UNPROVEN" if unproven else "PROVEN"
    return {
        "schemaVersion": "1.0",
        "verdict": verdict,
        "blocking": blocking,
        "unproven": unproven,
        "claimAudit": claims,
        "simplicityAudit": simplicity,
    }
