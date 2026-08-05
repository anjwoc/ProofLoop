from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from proofloop_core.context.io import read_json, write_json
from proofloop_core.contracts.run_policy import ResolvedRunPolicy, resolve_run_policy, write_effective_policy

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class InvocationContext:
    invocation_kind: str
    requested_host: str | None
    required_claim_types: tuple[str, ...]
    source_commit: str
    source_tree_hash: str
    runtime_bundle_hash: str
    policy_hash: str
    parent_process_id: int

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schemaVersion": SCHEMA_VERSION,
            "invocationKind": self.invocation_kind,
            "requestedHost": self.requested_host,
            "requiredClaimTypes": list(self.required_claim_types),
            "sourceCommit": self.source_commit,
            "sourceTreeHash": self.source_tree_hash,
            "runtimeBundleHash": self.runtime_bundle_hash,
            "policyHash": self.policy_hash,
            "parentProcessId": self.parent_process_id,
        }
        value["provenanceSha256"] = hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return value


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else "UNAVAILABLE"


def _runtime_bundle_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"UNREADABLE")
    return digest.hexdigest()


def create_invocation_context(
    repository: str | Path,
    policy: ResolvedRunPolicy,
    *,
    invocation_kind: str,
    requested_host: str | None,
    required_claim_types: Iterable[str] | None = None,
) -> InvocationContext:
    if invocation_kind not in {"CLI", "PROGRAMMATIC", "TEST_MECHANICS", "LIVE_ACCEPTANCE"}:
        raise ValueError(f"unsupported invocation kind: {invocation_kind}")
    repo = Path(repository).resolve()
    source_commit = _git(repo, "rev-parse", "HEAD")
    source_tree = _git(repo, "rev-parse", "HEAD^{tree}")
    claims = tuple(required_claim_types or policy.get("release.requiredClaimTypes"))
    return InvocationContext(
        invocation_kind=invocation_kind,
        requested_host=requested_host,
        required_claim_types=claims,
        source_commit=source_commit,
        source_tree_hash=source_tree,
        runtime_bundle_hash=_runtime_bundle_hash(),
        policy_hash=policy.sha256,
        parent_process_id=os.getpid(),
    )


def _prune_old_records(repo: Path, keep: int) -> None:
    proofloop_dir = repo / ".proofloop"
    if not proofloop_dir.exists():
        return
    for subdir_name in ("runs", "relay", "requests"):
        target_dir = proofloop_dir / subdir_name
        if not target_dir.exists():
            continue
        try:
            items = sorted(target_dir.iterdir(), key=lambda path: (path.stat().st_mtime, path.name))
        except OSError:
            continue
        for item in items[:-keep] if len(items) > keep else ():
            try:
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
            except OSError:
                continue


def start_run(
    repository: str | Path,
    request: str = "",
    *,
    policy: ResolvedRunPolicy | None = None,
    invocation_context: InvocationContext | None = None,
) -> dict[str, Any]:
    repo = Path(repository).resolve()
    resolved_policy = policy or resolve_run_policy()
    context = invocation_context or create_invocation_context(
        repo,
        resolved_policy,
        invocation_kind="PROGRAMMATIC",
        requested_host=None,
    )
    if context.policy_hash != resolved_policy.sha256:
        raise ValueError("POLICY_PROVENANCE_MISMATCH")
    _prune_old_records(repo, keep=int(resolved_policy.get("run.retainedRuns")))
    run_id = time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]
    run_dir = repo / ".proofloop" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    write_effective_policy(run_dir / "run-policy.json", resolved_policy)
    provenance = context.to_dict()
    write_json(run_dir / "run-provenance.json", provenance)
    state = {
        "schemaVersion": SCHEMA_VERSION,
        "runId": run_id,
        "runDir": str(run_dir),
        "repository": str(repo),
        "request": request,
        "status": "ACTIVE",
        "createdAtEpoch": time.time(),
        "invocationKind": context.invocation_kind,
        "hostRequested": context.requested_host,
        "policyHash": resolved_policy.sha256,
        "provenanceHash": provenance["provenanceSha256"],
    }
    write_json(run_dir / "run.json", state)
    write_json(repo / ".proofloop" / "active-run.json", state)
    return state


def load_active_run(repository: str | Path) -> dict[str, Any] | None:
    path = Path(repository).resolve() / ".proofloop" / "active-run.json"
    return read_json(path) if path.exists() else None


def finalize_run(repository: str | Path, truth_report: dict[str, Any]) -> None:
    repo = Path(repository).resolve()
    active_path = repo / ".proofloop" / "active-run.json"
    if not active_path.exists():
        return
    state = read_json(active_path)
    state["status"] = "FINALIZED"
    state["finalVerdict"] = truth_report.get("verdict")
    state["finalizedAtEpoch"] = time.time()
    write_json(Path(state["runDir"]) / "run.json", state)
    active_path.unlink(missing_ok=True)


def abort_run(repository: str | Path, reason: str) -> dict[str, Any]:
    repo = Path(repository).resolve()
    active = load_active_run(repo)
    if not active:
        return {"status": "NO_ACTIVE_RUN"}
    report = {"schemaVersion": SCHEMA_VERSION, "verdict": "BLOCKED", "reason": reason}
    write_json(Path(active["runDir"]) / "truth-report.json", report)
    finalize_run(repo, report)
    return report
