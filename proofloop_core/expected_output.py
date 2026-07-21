"""Machine-checkable acceptance contract for ``docs/roadmap/expected-output.md``.

The roadmap describes a user experience, not an API that can be compared byte
for byte.  This module deliberately verifies the durable parts of that
experience instead: the user can trace their unmodified request to the actual
repository, see the selected strategy and model evidence, and inspect the
parent-owned evidence behind the final Truth verdict.

It is intentionally conservative.  A syntactically valid report does not make
an incomplete run usable; terminal mutation runs must also expose verification
and Truth artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .live_evidence import validate_core_evidence
from .request_envelope import hash_raw_text


SCHEMA_VERSION = "1.0"
CONTRACT_SOURCE = "docs/roadmap/expected-output.md"


def verify_expected_output(
    run_dir: str | Path,
    *,
    expected_repository: str | Path | None = None,
    require_terminal: bool = False,
) -> dict[str, Any]:
    """Verify the observable ProofLoop contract for one run directory.

    ``require_terminal`` is for authenticated acceptance runs.  It upgrades
    the expectation from "the user can follow this run" to "the user received
    a current, evidence-backed final verdict".  It never upgrades a Truth
    verdict itself.
    """
    root = Path(run_dir).resolve()
    checks: list[dict[str, str]] = []

    def record(check_id: str, ok: bool, reason: str) -> None:
        checks.append({"id": check_id, "status": "PASS" if ok else "FAIL", "reason": reason})

    run = _read_object(root / "run.json")
    envelope = _read_object(root / "request-envelope.json")
    intent_gate = _read_object(root / "intent-gate.json")
    intent_contract = _read_object(root / "intent-contract.json")
    grounding = _read_object(root / "grounding-snapshot.json")
    strategy = _read_object(root / "strategy.json")
    events = _read_jsonl(root / "events.jsonl")

    expected_root = Path(expected_repository).resolve() if expected_repository is not None else None
    run_root = _resolved_path(run.get("repository"))
    envelope_root = _resolved_path(envelope.get("repoRoot"))
    grounding_root = _resolved_path(grounding.get("repoRoot"))
    roots_match = run_root is not None and run_root == envelope_root == grounding_root
    if expected_root is not None:
        roots_match = roots_match and run_root == expected_root
    record(
        "repository_binding",
        roots_match,
        "run, request envelope, and grounding reference the requested repository"
        if roots_match
        else "repository root differs between the run, envelope, grounding, or requested workspace",
    )

    raw_text = envelope.get("rawText")
    raw_hash = envelope.get("rawHash")
    request_id = envelope.get("requestId")
    request_matches = (
        isinstance(raw_text, str)
        and bool(raw_text.strip())
        and raw_hash == hash_raw_text(raw_text)
        and isinstance(request_id, str)
        and request_id == run.get("runId")
    )
    record(
        "immutable_request",
        request_matches,
        "raw request, hash, and run identity are preserved" if request_matches else "raw request envelope is missing, altered, or detached from the run",
    )

    gate_visible = (
        isinstance(intent_gate.get("intentKind"), str)
        and isinstance(intent_gate.get("clarity"), str)
        and isinstance(intent_gate.get("authority"), str)
        and isinstance(intent_gate.get("groundingRequired"), bool)
        and _has_events(events, "request.envelope_created", "intent_gate.started", "intent_gate.completed")
    )
    record(
        "intent_and_authority_visibility",
        gate_visible,
        "IntentGate and authority decision are persisted and emitted" if gate_visible else "IntentGate decision or its user-visible events are missing",
    )

    contract_visible = (
        intent_contract.get("originalRequest") == raw_text
        and isinstance(intent_contract.get("objective"), str)
        and bool(intent_contract.get("objective"))
        and isinstance(intent_contract.get("acceptanceCriteria"), list)
        and bool(intent_contract.get("acceptanceCriteria"))
        and isinstance(intent_contract.get("authorizationBoundary"), str)
    )
    record(
        "refined_intent_contract",
        contract_visible,
        "objective, acceptance criteria, and authority boundary are inspectable" if contract_visible else "refined intent contract is absent or not traceable to the raw request",
    )

    grounding_visible = (
        isinstance(grounding.get("requestId"), str)
        and grounding.get("requestId") == request_id
        and isinstance(grounding.get("detectedCommands"), dict)
        and _has_events(events, "grounding.started", "grounding.completed")
    )
    record(
        "grounding_wave_zero",
        grounding_visible,
        "repository grounding and detected verification surfaces are persisted" if grounding_visible else "grounding snapshot or its lifecycle events are missing",
    )

    brief_name = "execution-brief.json" if (root / "execution-brief.json").is_file() else "refined-request-shadow.json"
    brief = _read_object(root / brief_name)
    strategy_visible = (
        isinstance(strategy.get("tier"), str)
        and isinstance(strategy.get("strategy"), str)
        and _has_events(events, "strategy.selected")
        and isinstance(brief.get("objective"), dict)
        and isinstance(brief.get("acceptanceCriteria"), list)
        and isinstance(brief.get("scope"), dict)
    )
    record(
        "strategy_and_execution_brief",
        strategy_visible,
        "workload strategy and scoped execution brief are inspectable" if strategy_visible else "strategy selection or execution brief is missing",
    )

    roles_started = [event for event in events if event.get("type") == "role.started"]
    progress_events = [
        event
        for event in events
        if event.get("type") in {"role.progress", "session.update", "role.output"}
    ]
    projections = list((root / "prompt-projections").glob("*.json")) if (root / "prompt-projections").is_dir() else []
    progress_visible = not roles_started or (bool(progress_events) and bool(projections))
    record(
        "observable_role_progress",
        progress_visible,
        "active role progress and a rendered role prompt are available" if progress_visible else "a role started without a visible progress event or rendered prompt artifact",
    )

    model_events = [event for event in events if event.get("type") == "role.model_observed"]
    requested_events = [event for event in events if event.get("type") == "model.requested"]
    model_visible = not roles_started or (bool(requested_events) and bool(model_events))
    record(
        "model_trace_honesty",
        model_visible,
        "requested and observed-or-unavailable model evidence is emitted" if model_visible else "a role started without explicit requested and observed/unavailable model evidence",
    )

    private_reasoning = _private_reasoning_persisted(root / "invocations")
    record(
        "private_reasoning_redacted",
        not private_reasoning,
        "host transcripts contain no provider private reasoning blocks" if not private_reasoning else "provider private reasoning was retained in a host transcript",
    )

    truth = _read_object(root / "truth-report.json")
    terminal = bool(truth)
    mutation = intent_gate.get("authority") == "repository_mutation"
    terminal_visible = True
    if require_terminal:
        truth_verdict = truth.get("verdict")
        required_terminal = ("proof-graph.json", "verification-plan.json", "checks/checks.json", "diff-guard.json", "review.json", "claims.json")
        success_or_partial = truth_verdict in {"PROVEN", "PARTIAL"}
        blocked_or_failed = truth_verdict in {"BLOCKED", "FAILED"}
        terminal_event = (
            _has_events(events, "verdict.issued", "truth.completed", "run.completed")
            if success_or_partial
            else _has_events(events, "verdict.issued", "run.blocked" if truth_verdict == "BLOCKED" else "run.failed")
        )
        terminal_visible = (
            terminal
            and isinstance(truth_verdict, str)
            and terminal_event
        )
        if mutation and success_or_partial and terminal_visible:
            terminal_visible = all((root / item).is_file() for item in required_terminal)
        if mutation and success_or_partial and terminal_visible:
            core = validate_core_evidence(root)
            terminal_visible = core.get("status") == "VALID"
        if blocked_or_failed and terminal_visible:
            blockers = truth.get("blockers")
            terminal_visible = isinstance(blockers, list) and any(isinstance(item, str) and item for item in blockers)
        if terminal_visible and roles_started:
            invocations = _read_jsonl(root / "invocations.jsonl")
            model_summary = _read_object(root / "model-trace-summary.json")
            usage_summary = _read_object(root / "usage" / "usage-summary.json")
            raw_usage_totals = usage_summary.get("totals")
            usage_totals: dict[str, Any] = raw_usage_totals if isinstance(raw_usage_totals, dict) else {}
            terminal_visible = bool(invocations) and bool(model_summary) and all(
                isinstance(item.get("requestedModel"), str) and isinstance(item.get("modelEvidence"), str)
                for item in invocations
            )
            terminal_visible = terminal_visible and all(
                isinstance(usage_totals.get(field), int) and not isinstance(usage_totals.get(field), bool)
                for field in ("rawTotal", "budgetedTotal")
            )
    record(
        "evidence_backed_truth_verdict",
        terminal_visible,
        "terminal Truth verdict is backed by parent-owned evidence appropriate to its outcome" if terminal_visible else "terminal Truth verdict, current outcome evidence, or invocation model trace is missing",
    )

    failures = [item["id"] for item in checks if item["status"] == "FAIL"]
    if failures:
        status = "FAIL"
    elif require_terminal:
        status = "PASS"
    else:
        status = "PASS" if terminal else "IN_PROGRESS"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "contractSource": CONTRACT_SOURCE,
        "status": status,
        "runDir": str(root),
        "runId": run.get("runId"),
        "repository": str(run_root) if run_root is not None else None,
        "terminal": terminal,
        "truthVerdict": truth.get("verdict"),
        "requireTerminal": require_terminal,
        "checks": checks,
        "failures": failures,
    }


def write_expected_output_report(
    run_dir: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Verify a run and persist the report beside its immutable artifacts."""
    root = Path(run_dir).resolve()
    report = verify_expected_output(root, **kwargs)
    (root / "expected-output-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _read_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, dict):
            return []
        records.append(data)
    return records


def _has_events(events: list[dict[str, Any]], *event_types: str) -> bool:
    observed = {item.get("type") for item in events}
    return all(item in observed for item in event_types)


def _resolved_path(value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return Path(value).resolve()
    except OSError:
        return None


def _private_reasoning_persisted(invocations_dir: Path) -> bool:
    if not invocations_dir.is_dir():
        return False
    for path in invocations_dir.rglob("*.log"):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _contains_private_reasoning(value):
                return True
    return False


def _contains_private_reasoning(value: Any) -> bool:
    if isinstance(value, list):
        return any(_contains_private_reasoning(item) for item in value)
    if not isinstance(value, dict):
        return False
    # Host transcripts retain only an explicit, content-free redaction marker
    # for provider thinking blocks.  That marker proves the stream was
    # sanitized and must not make an otherwise safe artifact fail acceptance.
    if value.get("type") == "thinking":
        return value.get("redacted") is not True
    if "thinking" in value or "signature" in value:
        return True
    return any(_contains_private_reasoning(item) for item in value.values())
