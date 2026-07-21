from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from enum import Enum
from typing import AbstractSet, Any

SCHEMA_VERSION = "1.0"
COMPOSER_POLICY_VERSION = "1.0"
_REQUEST_FIELDS = frozenset({
    "schemaVersion", "requestId", "rawText", "rawHash", "receivedAt", "repoRoot",
    "hostRequested", "explicitPermissions", "explicitDenials", "userConstraints", "invocationSource"
})
_INTENT_FIELDS = {
    "schemaVersion", "originalRequest", "originalRequestHash", "objective",
    "acceptanceCriteria", "constraints", "nonGoals", "authorizationBoundary",
    "assumptions", "unknowns", "riskSignals", "targetArtifacts",
}
_BRIEF_FIELDS = {
    "schemaVersion", "kind", "provenance", "objective", "acceptanceCriteria",
    "constraints", "nonGoals", "authorizationBoundary", "assumptions", "unknowns",
    "riskSignals", "scope", "facts", "inferences", "openQuestions",
}
_PROVENANCE_FIELDS = {
    "requestArtifactSha256", "originalRequestSha256", "intentContractSha256",
    "strategySha256", "repositoryContextSha256", "repositoryBaseline",
    "composerPolicyVersion", "briefSha256",
}
_DIGEST_FIELDS = _PROVENANCE_FIELDS - {"repositoryBaseline", "composerPolicyVersion"}


class ProvenanceType(str, Enum):
    USER_EXPLICIT = "user_explicit"
    REPOSITORY_FACT = "repository_fact"
    PROOF_POLICY = "proof_policy"
    REVERSIBLE_DEFAULT = "reversible_default"
    MODEL_HYPOTHESIS = "model_hypothesis"


class ExecutionBriefValidationError(ValueError):
    """Raised when an execution-brief input or output violates the contract."""


def canonical_sha256(value: Any) -> str:
    _reject_floats(value, "value")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExecutionBriefValidationError(f"value is not canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def compose_execution_brief(
    *,
    request_artifact: Mapping[str, Any],
    intent_contract: Mapping[str, Any],
    strategy: Mapping[str, Any],
    repository_context: Mapping[str, Any],
    repository_baseline: str,
) -> dict[str, Any]:
    """Compose an unapproved shadow brief without mutating any input mapping."""
    request = _validate_request(request_artifact)
    intent = _validate_intent(intent_contract)
    _validate_opaque(strategy, "strategy")
    _validate_opaque(repository_context, "repository_context")
    _string(repository_baseline, "repository_baseline")
    request_hash = hashlib.sha256(request.encode("utf-8")).hexdigest()
    if intent["originalRequest"] != request:
        raise ExecutionBriefValidationError("intent originalRequest does not match request artifact")
    if intent["originalRequestHash"] != request_hash:
        raise ExecutionBriefValidationError("intent originalRequestHash does not match request artifact")

    provenance = {
        "requestArtifactSha256": canonical_sha256(dict(request_artifact)),
        "originalRequestSha256": request_hash,
        "intentContractSha256": canonical_sha256(dict(intent_contract)),
        "strategySha256": canonical_sha256(dict(strategy)),
        "repositoryContextSha256": canonical_sha256(dict(repository_context)),
        "repositoryBaseline": repository_baseline,
        "composerPolicyVersion": COMPOSER_POLICY_VERSION,
    }
    questions = [
        {
            "id": f"OQ-{index:03d}", "statement": statement, "blocking": True,
            "sourceRefs": [{"artifact": "intent-contract.json", "pointer": f"/unknowns/{index - 1}"}],
        }
        for index, statement in enumerate(intent["unknowns"], start=1)
    ]
    brief = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "EXECUTION_BRIEF_SHADOW",
        "provenance": provenance,
        "objective": {"statement": intent["objective"], "provenance": ProvenanceType.USER_EXPLICIT.value},
        "acceptanceCriteria": [
            {**ac, "provenance": ProvenanceType.USER_EXPLICIT.value} for ac in copy.deepcopy(intent["acceptanceCriteria"])
        ],
        "constraints": [{"statement": c, "provenance": ProvenanceType.USER_EXPLICIT.value} for c in intent["constraints"]],
        "nonGoals": [{"statement": c, "provenance": ProvenanceType.USER_EXPLICIT.value} for c in intent["nonGoals"]],
        "authorizationBoundary": {"statement": intent["authorizationBoundary"], "provenance": ProvenanceType.USER_EXPLICIT.value},
        "assumptions": [{"statement": c, "provenance": ProvenanceType.USER_EXPLICIT.value} for c in intent["assumptions"]],
        "unknowns": [{"statement": c, "provenance": ProvenanceType.USER_EXPLICIT.value} for c in intent["unknowns"]],
        "riskSignals": [{"statement": c, "provenance": ProvenanceType.USER_EXPLICIT.value} for c in intent["riskSignals"]],
        "scope": {
            "candidates": list(intent["targetArtifacts"]), "approvedPaths": [],
            "protectedPaths": [], "status": "UNRESOLVED",
        },
        "facts": [], "inferences": [], "openQuestions": questions,
    }
    provenance["briefSha256"] = _brief_sha256(brief)
    validate_execution_brief(brief)
    return brief


def validate_execution_brief(value: Mapping[str, Any]) -> None:
    _mapping(value, "execution brief")
    _exact(value, _BRIEF_FIELDS, "execution brief")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise ExecutionBriefValidationError("execution brief requires schemaVersion 1.0")
    if value.get("kind") not in ("EXECUTION_BRIEF_SHADOW", "EXECUTION_BRIEF"):
        raise ExecutionBriefValidationError("execution brief kind must be EXECUTION_BRIEF_SHADOW or EXECUTION_BRIEF")
    _provenanced_string(value.get("objective"), "execution brief objective")
    _provenanced_criteria(value.get("acceptanceCriteria"), "execution brief acceptanceCriteria")
    for field in ("constraints", "nonGoals", "assumptions", "unknowns", "riskSignals"):
        _provenanced_strings(value.get(field), f"execution brief {field}")
    _provenanced_string(value.get("authorizationBoundary"), "execution brief authorizationBoundary")
    provenance = value.get("provenance")
    _provenance(provenance)
    _scope(value.get("scope"), kind=str(value.get("kind")))
    _grounded(value.get("facts"), "facts")
    _grounded(value.get("inferences"), "inferences")
    _questions(value.get("openQuestions"))
    _reject_floats(value, "execution brief")
    assert isinstance(provenance, Mapping)
    if provenance["briefSha256"] != _brief_sha256(value):
        raise ExecutionBriefValidationError("execution brief briefSha256 does not match content")


def _brief_sha256(value: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(value))
    provenance = dict(payload["provenance"])
    provenance.pop("briefSha256", None)
    payload["provenance"] = provenance
    return canonical_sha256(payload)


def _validate_request(value: Mapping[str, Any]) -> str:
    _mapping(value, "request artifact")
    _exact(value, _REQUEST_FIELDS, "request artifact")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise ExecutionBriefValidationError("request artifact requires schemaVersion 1.0")
    request = value.get("rawText")
    if not isinstance(request, str):
        raise ExecutionBriefValidationError("request artifact rawText must be a string")
    return request


def _validate_intent(value: Mapping[str, Any]) -> dict[str, Any]:
    _mapping(value, "intent contract")
    _exact(value, _INTENT_FIELDS, "intent contract")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise ExecutionBriefValidationError("intent contract requires schemaVersion 1.0")
    for field in ("originalRequest", "originalRequestHash", "objective", "authorizationBoundary"):
        _string(value.get(field), f"intent contract {field}")
    if not re.fullmatch(r"[0-9a-f]{64}", value["originalRequestHash"]):
        raise ExecutionBriefValidationError("intent contract originalRequestHash must be lowercase SHA-256 hex")
    _criteria(value.get("acceptanceCriteria"), "intent contract acceptanceCriteria")
    for field in ("constraints", "nonGoals", "assumptions", "unknowns", "riskSignals", "targetArtifacts"):
        _strings(value.get(field), f"intent contract {field}")
    _reject_floats(value, "intent contract")
    return copy.deepcopy(dict(value))


def _criteria(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise ExecutionBriefValidationError(f"{label} must be a non-empty list")
    seen: set[str] = set()
    for index, item in enumerate(value):
        name = f"{label}[{index}]"
        _mapping(item, name)
        _exact(item, {"id", "statement"}, name)
        criterion_id = _string(item.get("id"), f"{name}.id")
        _string(item.get("statement"), f"{name}.statement")
        if criterion_id in seen:
            raise ExecutionBriefValidationError(f"{label} contains duplicate id {criterion_id}")
        seen.add(criterion_id)


def _provenanced_criteria(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise ExecutionBriefValidationError(f"{label} must be a non-empty list")
    seen: set[str] = set()
    for index, item in enumerate(value):
        name = f"{label}[{index}]"
        _mapping(item, name)
        _exact(item, {"id", "statement", "provenance"}, name)
        criterion_id = _string(item.get("id"), f"{name}.id")
        _string(item.get("statement"), f"{name}.statement")
        ProvenanceType(_string(item.get("provenance"), f"{name}.provenance"))
        if criterion_id in seen:
            raise ExecutionBriefValidationError(f"{label} contains duplicate id {criterion_id}")
        seen.add(criterion_id)


def _provenance(value: Any) -> None:
    _mapping(value, "execution brief provenance")
    _exact(value, _PROVENANCE_FIELDS, "execution brief provenance")
    for field in _PROVENANCE_FIELDS:
        _string(value.get(field), f"execution brief provenance.{field}")
    for field in _DIGEST_FIELDS:
        if not re.fullmatch(r"[0-9a-f]{64}", value[field]):
            raise ExecutionBriefValidationError(f"execution brief provenance.{field} must be lowercase SHA-256 hex")


def _scope(value: Any, *, kind: str) -> None:
    _mapping(value, "execution brief scope")
    _exact(value, {"candidates", "approvedPaths", "protectedPaths", "status"}, "execution brief scope")
    _strings(value.get("candidates"), "execution brief scope.candidates")
    approved = value.get("approvedPaths")
    protected = value.get("protectedPaths")
    _strings(approved, "execution brief scope.approvedPaths")
    _strings(protected, "execution brief scope.protectedPaths")
    if kind == "EXECUTION_BRIEF_SHADOW":
        if approved != [] or protected != []:
            raise ExecutionBriefValidationError("shadow execution brief cannot approve or protect paths")
        if value.get("status") != "UNRESOLVED":
            raise ExecutionBriefValidationError("shadow execution brief scope must remain UNRESOLVED")
        return
    if value.get("status") != "CONSTRAINED":
        raise ExecutionBriefValidationError("active execution brief scope must be CONSTRAINED")
    candidates = set(value["candidates"])
    if not set(approved).issubset(candidates):
        raise ExecutionBriefValidationError("active execution brief cannot approve paths outside candidates")
    if not set(protected).issubset(candidates):
        raise ExecutionBriefValidationError("active execution brief cannot protect paths outside candidates")
    if set(approved).intersection(protected):
        raise ExecutionBriefValidationError("active execution brief path cannot be both approved and protected")


def _grounded(value: Any, label: str) -> None:
    if not isinstance(value, list):
        raise ExecutionBriefValidationError(f"execution brief {label} must be a list")
    for index, item in enumerate(value):
        name = f"execution brief {label}[{index}]"
        _mapping(item, name)
        _exact(item, {"id", "statement", "sourceRefs"}, name)
        _string(item.get("id"), f"{name}.id")
        _string(item.get("statement"), f"{name}.statement")
        _refs(item.get("sourceRefs"), f"{name}.sourceRefs")


def _questions(value: Any) -> None:
    if not isinstance(value, list):
        raise ExecutionBriefValidationError("execution brief openQuestions must be a list")
    for index, item in enumerate(value):
        name = f"execution brief openQuestions[{index}]"
        _mapping(item, name)
        _exact(item, {"id", "statement", "blocking", "sourceRefs"}, name)
        _string(item.get("id"), f"{name}.id")
        _string(item.get("statement"), f"{name}.statement")
        if item.get("blocking") is not True:
            raise ExecutionBriefValidationError(f"{name}.blocking cannot be downgraded")
        _refs(item.get("sourceRefs"), f"{name}.sourceRefs")


def _refs(value: Any, label: str) -> None:
    if not isinstance(value, list) or not value:
        raise ExecutionBriefValidationError(f"{label} must be a non-empty list")
    for index, item in enumerate(value):
        name = f"{label}[{index}]"
        _mapping(item, name)
        _exact(item, {"artifact", "pointer"}, name)
        _string(item.get("artifact"), f"{name}.artifact")
        if not _string(item.get("pointer"), f"{name}.pointer").startswith("/"):
            raise ExecutionBriefValidationError(f"{name}.pointer must be a JSON pointer")


def _strings(value: Any, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ExecutionBriefValidationError(f"{label} must be a list of non-empty strings")


def _provenanced_string(value: Any, label: str) -> None:
    _mapping(value, label)
    _exact(value, {"statement", "provenance"}, label)
    _string(value.get("statement"), f"{label}.statement")
    ProvenanceType(_string(value.get("provenance"), f"{label}.provenance"))


def _provenanced_strings(value: Any, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ExecutionBriefValidationError(f"{label} must be a list of provenanced items")
    for index, item in enumerate(value):
        name = f"{label}[{index}]"
        _provenanced_string(item, name)


def _validate_opaque(value: Mapping[str, Any], label: str) -> None:
    _mapping(value, label)
    _reject_floats(value, label)
    canonical_sha256(dict(value))


def _mapping(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise ExecutionBriefValidationError(f"{label} must be a mapping")


def _exact(value: Mapping[str, Any], expected: AbstractSet[str], label: str) -> None:
    if set(value) != expected:
        raise ExecutionBriefValidationError(
            f"{label} fields are invalid: missing={sorted(expected - set(value))}, unknown={sorted(set(value) - expected)}"
        )


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ExecutionBriefValidationError(f"{label} must be a non-empty string")
    return value


def _reject_floats(value: Any, label: str) -> None:
    if isinstance(value, float):
        raise ExecutionBriefValidationError(f"{label} must not contain floats")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ExecutionBriefValidationError(f"{label} object keys must be strings")
            _reject_floats(item, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_floats(item, f"{label}[{index}]")
