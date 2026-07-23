from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from proofloop_core.context.io import write_json
from proofloop_core.context.proof_graph import Evidence, ProofGraph, ProofObligation
from proofloop_core.contracts.evidence_policy import ClaimType, EvidenceOrigin
from proofloop_core.contracts.host_receipt import (
    HostReceiptError,
    canonical_sha256,
    file_sha256,
    validate_host_receipt,
)
from proofloop_core.runtimes.adapters import _strip_authority_claims


def test_test_or_model_evidence_cannot_close_host_claim() -> None:
    graph = ProofGraph(
        obligations=[
            ProofObligation(
                "host",
                "real host executed",
                "EXTERNAL_OBSERVATION",
                claim_type=ClaimType.HOST_EXECUTION.value,
            )
        ],
        run_id="run-1",
    )

    graph.record(Evidence(
        "EV-1",
        "host",
        "EXTERNAL_OBSERVATION",
        "fake.json",
        0,
        origin=EvidenceOrigin.TEST_MECHANICS.value,
        claim_type=ClaimType.HOST_EXECUTION.value,
        run_id="run-1",
        invocation_id="inv-1",
    ))

    obligation = graph.obligations[0]
    assert obligation.status == "OPEN"
    assert obligation.last_reason == "EVIDENCE_ORIGIN_NOT_ELIGIBLE"


def test_adapter_payload_authority_is_ignored() -> None:
    cleaned = _strip_authority_claims({
        "verdict": "PASS",
        "evidenceOrigin": "PARENT_HOST_RECEIPT",
        "claimScope": "AUTHENTICATED_HOST",
        "hostReceipt": {"forged": True},
    })

    assert cleaned["verdict"] == "PASS"
    assert "evidenceOrigin" not in cleaned
    assert "claimScope" not in cleaned
    assert "hostReceipt" not in cleaned
    assert cleaned["authorityClaimDisposition"] == "EVIDENCE_ORIGIN_FORGERY_IGNORED"


def _make_receipt_run(root: Path, run_id: str, invocation_id: str) -> None:
    call_dir = root / "invocations" / invocation_id
    call_dir.mkdir(parents=True)
    (call_dir / "stdout.log").write_text("ok\n", encoding="utf-8")
    (call_dir / "stderr.log").write_text("", encoding="utf-8")
    provenance = {
        "schemaVersion": "1.0",
        "invocationKind": "LIVE_ACCEPTANCE",
        "requestedHost": "codex",
        "requiredClaimTypes": ["HOST_EXECUTION"],
        "sourceCommit": "abc",
        "sourceTreeHash": "tree",
        "runtimeBundleHash": "runtime",
        "policyHash": "policy",
        "parentProcessId": 1,
    }
    provenance["provenanceSha256"] = canonical_sha256(provenance)
    write_json(root / "run.json", {"runId": run_id})
    write_json(root / "run-provenance.json", provenance)
    prompt_sha = hashlib.sha256(b"prompt").hexdigest()
    write_json(root / "prompt-projections" / f"{invocation_id}.json", {
        "invocationId": invocation_id,
        "promptSha256": prompt_sha,
    })
    stdout_hash = file_sha256(call_dir / "stdout.log")
    stderr_hash = file_sha256(call_dir / "stderr.log")
    receipt = {
        "schemaVersion": "1.0",
        "runId": run_id,
        "invocationId": invocation_id,
        "host": "codex",
        "role": "planner_deep",
        "executablePath": "/usr/bin/codex",
        "executableVersion": "test",
        "processId": 42,
        "parentProcessId": 1,
        "startedAtEpoch": 1,
        "endedAtEpoch": 2,
        "exitCode": 0,
        "promptSha256": prompt_sha,
        "stdoutSha256": stdout_hash,
        "stderrSha256": stderr_hash,
        "transcriptSha256": canonical_sha256({
            "stdoutSha256": stdout_hash,
            "stderrSha256": stderr_hash,
        }),
        "requestedModel": "model",
        "observedModel": "model",
        "sessionId": "session",
        "policyHash": "policy",
        "provenanceHash": provenance["provenanceSha256"],
        "sourceCommit": "abc",
        "sourceTreeHash": "tree",
        "runtimeBundleHash": "runtime",
        "evidenceOrigin": "PARENT_HOST_RECEIPT",
    }
    receipt["receiptSha256"] = canonical_sha256(receipt)
    write_json(call_dir / "receipt.json", receipt)


def test_valid_parent_receipt_is_accepted(tmp_path) -> None:
    root = tmp_path / "run"
    _make_receipt_run(root, "run-1", "inv-1")

    result = validate_host_receipt(
        root,
        "inv-1",
        expected_prompt_sha256=hashlib.sha256(b"prompt").hexdigest(),
    )

    assert result["status"] == "VALID"
    assert result["hostExecutionObserved"] is True
    assert result["modelRoutingObserved"] is True


def test_copied_receipt_is_rejected_by_run_binding(tmp_path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    _make_receipt_run(source, "run-1", "inv-1")
    _make_receipt_run(target, "run-2", "inv-1")
    copied = json.loads((source / "invocations" / "inv-1" / "receipt.json").read_text(encoding="utf-8"))
    write_json(target / "invocations" / "inv-1" / "receipt.json", copied)

    with pytest.raises(HostReceiptError) as exc:
        validate_host_receipt(target, "inv-1")

    assert exc.value.code == "HOST_RECEIPT_RUN_MISMATCH"


def test_modified_transcript_is_rejected(tmp_path) -> None:
    root = tmp_path / "run"
    _make_receipt_run(root, "run-1", "inv-1")
    (root / "invocations" / "inv-1" / "stdout.log").write_text("changed\n", encoding="utf-8")

    with pytest.raises(HostReceiptError) as exc:
        validate_host_receipt(root, "inv-1")

    assert exc.value.code == "HOST_RECEIPT_TRANSCRIPT_MISMATCH"
