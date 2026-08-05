from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from proofloop_core.context.io import read_json, write_json

SCHEMA_VERSION = "1.0"


class HostReceiptError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _without_receipt_hash(receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(receipt)
    value.pop("receiptSha256", None)
    return value


def validate_host_receipt(
    run_dir: str | Path,
    invocation_id: str,
    *,
    expected_prompt_sha256: str | None = None,
) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    call_dir = root / "invocations" / invocation_id
    receipt_path = call_dir / "receipt.json"
    if not receipt_path.is_file():
        raise HostReceiptError("HOST_RECEIPT_MISSING", str(receipt_path))
    receipt = read_json(receipt_path)
    if not isinstance(receipt, dict) or receipt.get("schemaVersion") != SCHEMA_VERSION:
        raise HostReceiptError("HOST_RECEIPT_SCHEMA_INVALID", "receipt schemaVersion must be 1.0")

    observed_hash = canonical_sha256(_without_receipt_hash(receipt))
    if receipt.get("receiptSha256") != observed_hash:
        raise HostReceiptError("HOST_RECEIPT_HASH_MISMATCH", "receipt content changed after sealing")

    run = read_json(root / "run.json")
    provenance = read_json(root / "run-provenance.json")
    if receipt.get("runId") != run.get("runId"):
        raise HostReceiptError("HOST_RECEIPT_RUN_MISMATCH", "receipt belongs to another run")
    if receipt.get("invocationId") != invocation_id:
        raise HostReceiptError("HOST_RECEIPT_INVOCATION_MISMATCH", "receipt belongs to another invocation")
    if receipt.get("provenanceHash") != provenance.get("provenanceSha256"):
        raise HostReceiptError("HOST_RECEIPT_PROVENANCE_MISMATCH", "run provenance hash differs")
    if receipt.get("policyHash") != provenance.get("policyHash"):
        raise HostReceiptError("HOST_RECEIPT_POLICY_MISMATCH", "policy hash differs")
    for field in ("sourceCommit", "sourceTreeHash", "runtimeBundleHash"):
        if receipt.get(field) != provenance.get(field):
            raise HostReceiptError("HOST_RECEIPT_RUNTIME_MISMATCH", f"{field} differs")

    prompt_sha = receipt.get("promptSha256")
    if expected_prompt_sha256 is not None and prompt_sha != expected_prompt_sha256:
        raise HostReceiptError("HOST_RECEIPT_PROMPT_MISMATCH", "sent prompt differs from parent projection")
    projection_path = root / "prompt-projections" / f"{invocation_id}.json"
    if projection_path.is_file():
        projection = read_json(projection_path)
        if projection.get("promptSha256") != prompt_sha:
            raise HostReceiptError("HOST_RECEIPT_PROMPT_MISMATCH", "stored projection differs from receipt")

    stdout_path = call_dir / "stdout.log"
    stderr_path = call_dir / "stderr.log"
    if not stdout_path.is_file() or not stderr_path.is_file():
        raise HostReceiptError("HOST_RECEIPT_TRANSCRIPT_MISSING", "stdout or stderr transcript missing")
    stdout_hash = file_sha256(stdout_path)
    stderr_hash = file_sha256(stderr_path)
    if receipt.get("stdoutSha256") != stdout_hash or receipt.get("stderrSha256") != stderr_hash:
        raise HostReceiptError("HOST_RECEIPT_TRANSCRIPT_MISMATCH", "transcript bytes changed")
    transcript_hash = canonical_sha256({"stdoutSha256": stdout_hash, "stderrSha256": stderr_hash})
    if receipt.get("transcriptSha256") != transcript_hash:
        raise HostReceiptError("HOST_RECEIPT_TRANSCRIPT_MISMATCH", "combined transcript hash differs")

    process_id = receipt.get("processId")
    if not isinstance(process_id, int) or isinstance(process_id, bool) or process_id <= 0:
        raise HostReceiptError("HOST_RECEIPT_PROCESS_INVALID", "child process identifier is missing")
    executable = receipt.get("executablePath")
    if not isinstance(executable, str) or not executable or not Path(executable).is_absolute():
        raise HostReceiptError("HOST_RECEIPT_EXECUTABLE_INVALID", "resolved executable path is missing")
    if receipt.get("evidenceOrigin") != "PARENT_HOST_RECEIPT":
        raise HostReceiptError("HOST_RECEIPT_ORIGIN_INVALID", "origin is not parent-owned")

    return {
        "status": "VALID",
        "receipt": receipt,
        "receiptPath": str(receipt_path),
        "hostExecutionObserved": True,
        "modelRoutingObserved": bool(receipt.get("observedModel")),
    }


def seal_acp_receipt(
    *,
    run_dir: str | Path,
    invocation_id: str,
    role: str,
    runtime: str,
    prompt: str,
    result: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal parent-observed ACP/session facts without trusting model payload authority."""

    root = Path(run_dir).resolve()
    call_dir = root / "invocations" / invocation_id
    call_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = call_dir / "stdout.log"
    stderr_path = call_dir / "stderr.log"
    stdout_path.touch(exist_ok=True)
    stderr_path.touch(exist_ok=True)
    run = read_json(root / "run.json")
    provenance = read_json(root / "run-provenance.json")
    receipt = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run.get("runId") or root.name,
        "invocationId": invocation_id,
        "host": runtime,
        "role": role,
        "transport": "acp",
        "executablePath": str(Path(__file__).resolve()),
        "executableVersion": "ACP_SESSION",
        "processId": int(result.get("processId") or provenance.get("parentProcessId") or 0),
        "parentProcessId": provenance.get("parentProcessId"),
        "startedAtEpoch": result.get("startedAtEpoch"),
        "endedAtEpoch": result.get("endedAtEpoch"),
        "exitCode": result.get("exitCode", 0 if result.get("verdict") == "PASS" else 1),
        "promptSha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "stdoutSha256": file_sha256(stdout_path),
        "stderrSha256": file_sha256(stderr_path),
        "transcriptSha256": canonical_sha256({
            "stdoutSha256": file_sha256(stdout_path),
            "stderrSha256": file_sha256(stderr_path),
        }),
        "requestedModel": result.get("requestedModel"),
        "observedModel": result.get("observedModel"),
        "sessionId": result.get("sessionId"),
        "policyHash": provenance.get("policyHash"),
        "provenanceHash": provenance.get("provenanceSha256"),
        "sourceCommit": provenance.get("sourceCommit"),
        "sourceTreeHash": provenance.get("sourceTreeHash"),
        "runtimeBundleHash": provenance.get("runtimeBundleHash"),
        "evidenceOrigin": "PARENT_HOST_RECEIPT",
    }
    receipt["receiptSha256"] = canonical_sha256(receipt)
    write_json(call_dir / "receipt.json", receipt)
    return receipt
