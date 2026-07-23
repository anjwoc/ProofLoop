from __future__ import annotations

from proofloop_core.engine.repair import RepairAction, RepairState, decide_state, rule_ids


def _attempt(
    role: str,
    *,
    checks: str = "FAIL",
    diff: str = "PASS",
    fingerprint: str = "same",
    classification: str | None = None,
) -> dict:
    return {
        "role": role,
        "checkVerdict": checks,
        "diffVerdict": diff,
        "failureFingerprint": fingerprint,
        "classification": classification,
        "checksRef": f"attempt-{role}-checks.json",
        "diffGuardRef": f"attempt-{role}-diff.json",
    }


def test_decision_table_has_unique_stable_rule_ids() -> None:
    ids = rule_ids()
    assert ids
    assert len(ids) == len(set(ids))
    assert ids[0] == "R00_INITIAL_FAST"
    assert ids[-1] == "R99_BUDGET_EXHAUSTED"


def test_initial_state_runs_fast() -> None:
    decision = decide_state(RepairState.from_attempts([], max_fast_attempts=1, max_recovery_attempts=0))
    assert decision.action == RepairAction.RUN_FAST
    assert decision.rule_id == "R00_INITIAL_FAST"


def test_deterministic_success_enters_review() -> None:
    state = RepairState.from_attempts(
        [_attempt("implementer_fast", checks="PASS", diff="PASS", fingerprint="none")],
        max_fast_attempts=1,
        max_recovery_attempts=0,
    )
    decision = decide_state(state)
    assert decision.action == RepairAction.REVIEW
    assert decision.rule_id == "R10_DETERMINISTIC_SUCCESS"


def test_identical_failure_never_retries_same_role() -> None:
    attempts = [
        _attempt("implementer_fast", fingerprint="abc"),
        _attempt("implementer_fast", fingerprint="abc"),
    ]
    state = RepairState.from_attempts(attempts, max_fast_attempts=3, max_recovery_attempts=1)
    assert state.evidence_delta is False

    decision = decide_state(state)
    assert decision.action == RepairAction.RUN_RECOVERY
    assert decision.rule_id == "R30_IDENTICAL_FAST_TO_RECOVERY"


def test_identical_recovery_failure_blocks_when_no_new_evidence() -> None:
    attempts = [
        _attempt("implementer_recovery", fingerprint="abc"),
        _attempt("implementer_recovery", fingerprint="abc"),
    ]
    decision = decide_state(
        RepairState.from_attempts(attempts, max_fast_attempts=1, max_recovery_attempts=2)
    )
    assert decision.action == RepairAction.BLOCKED
    assert decision.rule_id == "R31_IDENTICAL_FAILURE_BLOCK"


def test_owner_decision_precedes_retry_budget() -> None:
    state = RepairState.from_attempts(
        [_attempt("implementer_fast", classification="SPEC_AMBIGUITY")],
        max_fast_attempts=3,
        max_recovery_attempts=2,
    )
    decision = decide_state(state)
    assert decision.action == RepairAction.RETURN_TO_PLANNER
    assert decision.rule_id == "R20_OWNER_DECISION"
