from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterator, Protocol
from collections.abc import Sequence

from proofloop_core.contracts.capability_contract import evaluate_capability, validate_records, ValidatedRecordSet

if TYPE_CHECKING:
    from proofloop_core.runtimes.adapters import RoleInvocation


@dataclass(frozen=True)
class HostCapability:
    host_name: str
    version: str | None

    supports_streaming: bool
    supports_structured_output: bool
    supports_subagents: bool
    supports_model_selection: bool
    supports_tool_restriction: bool
    supports_session_resume: bool
    supports_json_output: bool
    supports_worktree_isolation: bool
    supports_prompt_injection: bool

    available_models: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class HostRunHandle:
    invocation_id: str
    host_name: str
    role: str
    internal_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class HostEvent:
    event_type: str
    message: str
    data: dict[str, Any]


@dataclass(frozen=True)
class HostResult:
    payload: dict[str, Any]


class HostAdapterV2(Protocol):
    def detect_capabilities(self) -> HostCapability:
        ...

    def start_role(self, invocation: RoleInvocation) -> HostRunHandle:
        ...

    def stream_events(self, handle: HostRunHandle) -> Iterator[HostEvent]:
        ...

    def cancel(self, handle: HostRunHandle) -> None:
        ...

    def collect_result(self, handle: HostRunHandle) -> HostResult:
        ...


def build_capability_records(cap: HostCapability) -> ValidatedRecordSet:
    """Builds a ValidatedRecordSet from HostCapability."""
    records = []
    def add_record(dim: str, val: Any, rec_id: str):
        records.append({
            "schemaVersion": "1.0",
            "recordType": "CAPABILITY",
            "recordId": rec_id,
            "subject": {"runtime": cap.host_name, "runtimeVersion": cap.version},
            "dimension": dim,
            "scope": "RUNTIME",
            "value": val,
            "state": "DECLARED",
            "source": {"kind": "DECLARATION"}
        })

    for i, model in enumerate(cap.available_models):
        add_record("MODEL_SELECTION", model, f"model-{i}")
    
    if cap.supports_session_resume:
        add_record("ACCESS_POLICY", "SESSION_RESUME", "cap-session-resume")
    if cap.supports_structured_output or cap.supports_json_output:
        add_record("TRANSPORT", "STRUCTURED_OUTPUT", "cap-struct-out")
    
    return validate_records(records)


def match_capability(
    cap: HostCapability,
    requested_model: str,
    required_features: Sequence[str],
) -> dict[str, Any]:
    records = build_capability_records(cap)
    
    overall_disposition = "ALLOW"
    reasons: set[str] = set()

    if requested_model:
        model_claim = {
            "claimType": "GENERIC",
            "dimension": "MODEL_SELECTION",
            "requiredState": "DECLARED",
            "requestedValue": requested_model,
            "onUnproven": "DOWNGRADE"
        }
        model_eval = evaluate_capability(records, model_claim, fallback={"model": "fallback-model"})
        if model_eval.execution_disposition == "BLOCK":
            overall_disposition = "BLOCK"
        elif model_eval.execution_disposition == "DOWNGRADE" and overall_disposition != "BLOCK":
            overall_disposition = "DOWNGRADE"
        reasons.update(model_eval.reason_codes)

    for feature in required_features:
        dim = "TRANSPORT" if feature == "STRUCTURED_OUTPUT" else "ACCESS_POLICY"
        claim = {
            "claimType": "GENERIC",
            "dimension": dim,
            "requiredState": "DECLARED",
            "requestedValue": feature,
            "onUnproven": "BLOCK"
        }
        feat_eval = evaluate_capability(records, claim)
        if feat_eval.execution_disposition == "BLOCK":
            overall_disposition = "BLOCK"
        elif feat_eval.execution_disposition == "DOWNGRADE" and overall_disposition != "BLOCK":
            overall_disposition = "DOWNGRADE"
        reasons.update(feat_eval.reason_codes)

    return {
        "disposition": overall_disposition,
        "reasons": sorted(reasons),
    }
