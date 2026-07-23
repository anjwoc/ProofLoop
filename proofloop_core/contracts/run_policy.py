from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"
_SHIPPED_POLICY = Path(__file__).resolve().parents[1] / "config" / "default-run-policy.json"
_REQUIRED_ROLES = {
    "classifier_fast",
    "explorer_fast",
    "planner_deep",
    "implementer_fast",
    "implementer_recovery",
    "reviewer_deep",
}
_REQUIRED_TOP_LEVEL = {
    "schemaVersion",
    "policyVersion",
    "run",
    "goal",
    "roles",
    "prompt",
    "evidence",
    "hooks",
    "relay",
    "release",
}


class RunPolicyError(ValueError):
    """Raised before run creation when operational policy is invalid."""


@dataclass(frozen=True)
class ResolvedRunPolicy:
    values: dict[str, Any]
    sources: dict[str, str]
    sha256: str

    def get(self, dotted_path: str) -> Any:
        current: Any = self.values
        for token in dotted_path.split("."):
            if not isinstance(current, Mapping) or token not in current:
                raise RunPolicyError(f"POLICY_SCHEMA_INVALID: missing {dotted_path}")
            current = current[token]
        return copy.deepcopy(current)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "policyVersion": self.values["policyVersion"],
            "sha256": self.sha256,
            "values": copy.deepcopy(self.values),
            "sources": dict(sorted(self.sources.items())),
        }


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunPolicyError(f"POLICY_SCHEMA_INVALID: cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunPolicyError("POLICY_SCHEMA_INVALID: policy root must be an object")
    return value


def _flatten(value: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(item, Mapping):
            result.update(_flatten(item, path))
        else:
            result[path] = item
    return result


def _set_dotted(target: dict[str, Any], dotted: str, value: Any) -> None:
    tokens = dotted.split(".")
    current = target
    for token in tokens[:-1]:
        child = current.get(token)
        if not isinstance(child, dict):
            raise RunPolicyError(f"POLICY_SCHEMA_INVALID: override path {dotted} is not declared")
        current = child
    leaf = tokens[-1]
    if leaf not in current:
        raise RunPolicyError(f"POLICY_SCHEMA_INVALID: override path {dotted} is not declared")
    current[leaf] = copy.deepcopy(value)


def _positive_int(value: Any, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RunPolicyError(f"POLICY_SCHEMA_INVALID: {path} must be a positive integer")
    return value


def _validate_exact(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RunPolicyError(f"POLICY_SCHEMA_INVALID: {path} must be an object")
    if set(value) != expected:
        raise RunPolicyError(
            f"POLICY_SCHEMA_INVALID: {path} fields invalid; "
            f"missing={sorted(expected - set(value))}, unknown={sorted(set(value) - expected)}"
        )
    return value


def validate_policy(value: Mapping[str, Any]) -> None:
    if set(value) != _REQUIRED_TOP_LEVEL:
        raise RunPolicyError(
            "POLICY_SCHEMA_INVALID: top-level fields invalid; "
            f"missing={sorted(_REQUIRED_TOP_LEVEL - set(value))}, "
            f"unknown={sorted(set(value) - _REQUIRED_TOP_LEVEL)}"
        )
    if value.get("schemaVersion") != SCHEMA_VERSION:
        raise RunPolicyError("POLICY_SCHEMA_INVALID: schemaVersion must be 1.0")
    if not isinstance(value.get("policyVersion"), str) or not value["policyVersion"]:
        raise RunPolicyError("POLICY_SCHEMA_INVALID: policyVersion must be non-empty")

    run = _validate_exact(value["run"], {"timeoutSeconds", "retainedRuns"}, "run")
    goal = _validate_exact(value["goal"], {"maxCycles", "maxReplans"}, "goal")
    evidence = _validate_exact(value["evidence"], {"maxFiles", "maxTotalBytes", "readChunkBytes"}, "evidence")
    hooks = _validate_exact(value["hooks"], {"timeoutSeconds"}, "hooks")
    relay = _validate_exact(value["relay"], {"intervalSeconds"}, "relay")
    prompt = _validate_exact(value["prompt"], {"activeTiers"}, "prompt")
    release = _validate_exact(value["release"], {"requiredClaimTypes"}, "release")

    for path, item in {
        "run.timeoutSeconds": run["timeoutSeconds"],
        "run.retainedRuns": run["retainedRuns"],
        "goal.maxCycles": goal["maxCycles"],
        "goal.maxReplans": goal["maxReplans"],
        "evidence.maxFiles": evidence["maxFiles"],
        "evidence.maxTotalBytes": evidence["maxTotalBytes"],
        "evidence.readChunkBytes": evidence["readChunkBytes"],
        "hooks.timeoutSeconds": hooks["timeoutSeconds"],
        "relay.intervalSeconds": relay["intervalSeconds"],
    }.items():
        _positive_int(item, path)

    roles = value.get("roles")
    if not isinstance(roles, dict) or set(roles) != _REQUIRED_ROLES:
        raise RunPolicyError(
            "POLICY_SCHEMA_INVALID: roles must contain exactly " + ", ".join(sorted(_REQUIRED_ROLES))
        )
    for role, role_policy in roles.items():
        role_policy = _validate_exact(role_policy, {"timeoutSeconds", "tokenBudget"}, f"roles.{role}")
        _positive_int(role_policy["timeoutSeconds"], f"roles.{role}.timeoutSeconds")
        _positive_int(role_policy["tokenBudget"], f"roles.{role}.tokenBudget")

    active_tiers = prompt["activeTiers"]
    if not isinstance(active_tiers, list) or set(active_tiers) != {"T0", "T1", "T2", "T3"}:
        raise RunPolicyError("POLICY_SCHEMA_INVALID: prompt.activeTiers must contain T0-T3")
    claims = release["requiredClaimTypes"]
    if not isinstance(claims, list) or not claims or any(not isinstance(item, str) or not item for item in claims):
        raise RunPolicyError("POLICY_SCHEMA_INVALID: release.requiredClaimTypes must be non-empty strings")


def resolve_run_policy(
    *,
    policy_file: str | Path | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> ResolvedRunPolicy:
    shipped = _load(_SHIPPED_POLICY)
    validate_policy(shipped)
    values = copy.deepcopy(shipped)
    sources = {path: "shipped" for path in _flatten(values)}

    if policy_file is not None:
        file_values = _load(Path(policy_file).resolve())
        for path, item in _flatten(file_values).items():
            if path in {"schemaVersion", "policyVersion"}:
                if item != values[path]:
                    raise RunPolicyError(f"POLICY_SCHEMA_INVALID: {path} cannot be overridden")
                continue
            _set_dotted(values, path, item)
            sources[path] = "file"

    for path, item in (cli_overrides or {}).items():
        if item is None:
            continue
        _set_dotted(values, path, item)
        sources[path] = "cli"

    validate_policy(values)
    return ResolvedRunPolicy(values=values, sources=sources, sha256=canonical_sha256(values))


def write_effective_policy(path: str | Path, policy: ResolvedRunPolicy) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
