from __future__ import annotations

import copy
import json

import pytest

from proofloop_core.contracts.run_policy import (
    RunPolicyError,
    canonical_sha256,
    resolve_run_policy,
    validate_policy,
)


def test_shipped_policy_is_stable_and_complete() -> None:
    first = resolve_run_policy()
    second = resolve_run_policy()

    assert first.sha256 == second.sha256 == canonical_sha256(first.values)
    assert first.get("prompt.activeTiers") == ["T0", "T1", "T2", "T3"]
    assert first.get("release.requiredClaimTypes")
    assert set(first.sources.values()) == {"shipped"}


def test_file_and_cli_overrides_record_their_source(tmp_path) -> None:
    override = tmp_path / "policy.json"
    override.write_text(
        json.dumps({"goal": {"maxCycles": 5}, "run": {"timeoutSeconds": 900}}),
        encoding="utf-8",
    )

    policy = resolve_run_policy(
        policy_file=override,
        cli_overrides={"goal.maxReplans": 1},
    )

    assert policy.get("goal.maxCycles") == 5
    assert policy.get("run.timeoutSeconds") == 900
    assert policy.get("goal.maxReplans") == 1
    assert policy.sources["goal.maxCycles"] == "file"
    assert policy.sources["run.timeoutSeconds"] == "file"
    assert policy.sources["goal.maxReplans"] == "cli"


def test_missing_required_field_fails_without_fallback() -> None:
    policy = resolve_run_policy().values
    broken = copy.deepcopy(policy)
    del broken["goal"]["maxCycles"]

    with pytest.raises(RunPolicyError, match="POLICY_SCHEMA_INVALID"):
        validate_policy(broken)


def test_unknown_override_cannot_create_hidden_policy() -> None:
    with pytest.raises(RunPolicyError, match="not declared"):
        resolve_run_policy(cli_overrides={"goal.secretRetries": 99})
