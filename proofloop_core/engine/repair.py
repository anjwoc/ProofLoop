from __future__ import annotations

from typing import Any


def decide_next(attempts: list[dict[str, Any]], max_fast_attempts: int = 2, max_recovery_attempts: int = 1) -> dict[str, Any]:
    if not attempts:
        return {"action": "RUN_FAST", "reason": "no attempts recorded"}

    latest = attempts[-1]
    if latest.get("checkVerdict") == "PASS" and latest.get("diffVerdict") == "PASS":
        return {"action": "REVIEW", "reason": "deterministic checks and diff guard passed"}

    classification = latest.get("classification")
    if classification in {
        "DESIGN_CONFLICT", "SPEC_AMBIGUITY", "CONTRACT_CHANGE",
        "AUTHORIZATION_AMBIGUOUS", "REPOSITORY_FACTS_CONFLICT",
        "REPEATED_FAILURE_INVALIDATES_HYPOTHESIS"
    }:
        return {"action": "RETURN_TO_PLANNER", "reason": classification}

    fast = [item for item in attempts if item.get("role") == "implementer_fast"]
    recovery = [item for item in attempts if item.get("role") == "implementer_recovery"]
    fingerprint = latest.get("failureFingerprint")

    all_repeats = sum(1 for item in attempts if fingerprint and item.get("failureFingerprint") == fingerprint)
    if all_repeats >= 3:
        return {"action": "BLOCKED", "reason": "same failure fingerprint repeated 3 times"}

    fast_repeats = sum(1 for item in fast if fingerprint and item.get("failureFingerprint") == fingerprint)

    if latest.get("role") == "implementer_fast":
        if fast_repeats >= 2 or len(fast) >= max_fast_attempts:
            if max_recovery_attempts > len(recovery):
                return {"action": "RUN_RECOVERY", "reason": "repeated fast failure or fast budget exhausted"}
            return {"action": "BLOCKED", "reason": "recovery budget unavailable"}
        return {"action": "RETRY_FAST", "reason": "fast attempt failed within retry budget"}

    if latest.get("role") == "implementer_recovery":
        if len(recovery) >= max_recovery_attempts:
            return {"action": "BLOCKED", "reason": "recovery attempt failed and budget exhausted"}
        return {"action": "RETRY_RECOVERY", "reason": "recovery failed within budget"}

    return {"action": "BLOCKED", "reason": "unknown attempt role"}
