from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

SCHEMA_VERSION = "1.0"
_MAX_FILES = 256
_MAX_TOTAL_BYTES = 64 * 1024 * 1024  # 64 MiB
_READ_CHUNK = 65536
_MANIFEST_REQUIRED_KEYS = {"schemaVersion", "artifacts"}
_MANIFEST_ALLOWED_KEYS = _MANIFEST_REQUIRED_KEYS | {
    "cycleId", "runId", "host", "scenario", "baselineCommit",
    "process", "sessionIds", "capabilities", "sealedAt",
    "bundleHash", "verdict", "evidenceLevel",
}
_ARTIFACT_REQUIRED_KEYS = {"path", "sha256", "sizeBytes"}
_ARTIFACT_ALLOWED_KEYS = _ARTIFACT_REQUIRED_KEYS

CORE_EVIDENCE_DIR = "core-evidence"
CORE_EVIDENCE_MANIFEST = "live-evidence.json"
CORE_EVIDENCE_SOURCE_MAP = "source-map.json"
CORE_EVIDENCE_PLAN = "verification-plan.json"


class ValidationResult(NamedTuple):
    """Immutable result of L1 bundle structural validation."""
    status: str  # STRUCTURALLY_VALID | REJECTED
    reasons: tuple[str, ...]  # stable sorted reason codes
    candidate_digest: str | None  # canonical SHA-256 or None on rejection


class LiveEvidenceValidationError(ValueError):
    """Raised for fatal programming errors in validator usage."""


# ---------------------------------------------------------------------------
# Stable reason codes
# ---------------------------------------------------------------------------

REJECTED_SCHEMA_VIOLATION = "REJECTED_SCHEMA_VIOLATION"
REJECTED_BUNDLE_LIMIT_EXCEEDED = "REJECTED_BUNDLE_LIMIT_EXCEEDED"
REJECTED_PATH_SECURITY_VIOLATION = "REJECTED_PATH_SECURITY_VIOLATION"
REJECTED_PATH_COLLISION = "REJECTED_PATH_COLLISION"
REJECTED_FILE_TYPE_VIOLATION = "REJECTED_FILE_TYPE_VIOLATION"
REJECTED_MISSING_ARTIFACT = "REJECTED_MISSING_ARTIFACT"
REJECTED_UNEXPECTED_ARTIFACT = "REJECTED_UNEXPECTED_ARTIFACT"
REJECTED_HASH_MISMATCH = "REJECTED_HASH_MISMATCH"
REJECTED_SIZE_MISMATCH = "REJECTED_SIZE_MISMATCH"
REJECTED_MALFORMED_JSON = "REJECTED_MALFORMED_JSON"
REJECTED_MALFORMED_JSONL = "REJECTED_MALFORMED_JSONL"

CORE_EVIDENCE_MISSING = "CORE_EVIDENCE_MISSING"
CORE_EVIDENCE_SOURCE_MISMATCH = "CORE_EVIDENCE_SOURCE_MISMATCH"
CORE_EVIDENCE_PLAN_MISMATCH = "CORE_EVIDENCE_PLAN_MISMATCH"
CORE_EVIDENCE_MANDATORY_CHECK_MISSING = "CORE_EVIDENCE_MANDATORY_CHECK_MISSING"
CORE_EVIDENCE_EVALUATOR_CHANGED = "CORE_EVIDENCE_EVALUATOR_CHANGED"
CORE_EVIDENCE_SEMANTIC_INVALID = "CORE_EVIDENCE_SEMANTIC_INVALID"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_bundle(
    bundle_root: Path,
    manifest: Mapping[str, Any],
) -> ValidationResult:
    """Validate a candidate evidence bundle at L1 (structural integrity).

    The validator does NOT use the manifest's own ``verdict``,
    ``evidenceLevel``, or ``bundleHash`` as judgment inputs. It computes
    a ``candidateDigest`` independently.

    Returns an immutable ``ValidationResult``.
    """
    reasons: list[str] = []

    # Stage 1 — manifest schema
    _validate_manifest_schema(manifest, reasons)
    if reasons:
        return _rejected(reasons)

    artifacts: list[dict[str, Any]] = list(manifest["artifacts"])

    # Stage 2 — path lexical checks and collision detection
    _validate_paths(artifacts, reasons)

    # Stage 2b — bundle limits (check before filesystem access)
    if len(artifacts) > _MAX_FILES:
        reasons.append(REJECTED_BUNDLE_LIMIT_EXCEEDED)

    if reasons:
        return _rejected(reasons)

    # Stage 3 — bundle tree: missing, unexpected, type, and limits
    declared_paths = {a["path"] for a in artifacts}
    _validate_tree(bundle_root, declared_paths, reasons)

    if reasons:
        return _rejected(reasons)

    # Stages 4-6 — per-file: type, hash, size, json/jsonl syntax
    total_bytes = 0
    digest_entries: list[dict[str, Any]] = []

    for descriptor in sorted(artifacts, key=lambda a: a["path"]):
        file_path = bundle_root / descriptor["path"]
        file_reasons, file_size, file_hash = _validate_file(
            file_path, descriptor,
        )
        reasons.extend(file_reasons)
        total_bytes += file_size
        digest_entries.append({
            "path": descriptor["path"],
            "sha256": file_hash,
            "sizeBytes": file_size,
        })

    if total_bytes > _MAX_TOTAL_BYTES:
        reasons.append(REJECTED_BUNDLE_LIMIT_EXCEEDED)

    if reasons:
        return _rejected(reasons)

    # Stage 7 — canonical candidate digest (excluding self-claims)
    candidate_digest = _compute_candidate_digest(digest_entries)

    return ValidationResult(
        status="STRUCTURALLY_VALID",
        reasons=(),
        candidate_digest=candidate_digest,
    )


def seal_core_evidence(
    run_dir: Path,
    *,
    checks: Mapping[str, Any],
    diff: Mapping[str, Any],
    verification_plan: Mapping[str, Any],
    baseline_commit: str | None,
) -> dict[str, Any]:
    """Capture parent-owned verification output into a sealed evidence bundle.

    The agent-facing run directory is not a trust boundary.  This function is
    invoked by the parent immediately after deterministic checks complete and
    copies the Core-produced report, logs, diff result, and in-memory
    verification plan into a separate manifest-backed bundle.  Later truth
    evaluation revalidates both the bundle and the source files, so a write
    after capture cannot silently promote a verdict.
    """
    root = Path(run_dir).resolve()
    checks_path = root / "checks" / "checks.json"
    diff_path = root / "diff-guard.json"
    _require_json_matches(checks_path, checks)
    _require_json_matches(diff_path, diff)

    sources: dict[str, Path] = {
        "checks.json": checks_path,
        "diff-guard.json": diff_path,
    }
    results = checks.get("checks")
    if not isinstance(results, list):
        raise LiveEvidenceValidationError("checks report does not contain a checks list")
    for index, item in enumerate(results, start=1):
        if not isinstance(item, Mapping):
            raise LiveEvidenceValidationError("checks report contains a non-object result")
        for stream in ("stdoutRef", "stderrRef"):
            raw_path = item.get(stream)
            if not isinstance(raw_path, str) or not raw_path:
                raise LiveEvidenceValidationError(f"checks report is missing {stream}")
            source = Path(raw_path).resolve()
            try:
                source.relative_to(root)
            except ValueError as exc:
                raise LiveEvidenceValidationError(f"check log escapes run directory: {source}") from exc
            if not source.is_file():
                raise LiveEvidenceValidationError(f"check log is missing: {source}")
            sources[f"logs/{index:03d}-{stream}.log"] = source

    bundle_root = root / CORE_EVIDENCE_DIR
    temporary_root = Path(tempfile.mkdtemp(prefix=".core-evidence-", dir=root))
    try:
        source_map: dict[str, str] = {}
        descriptors: list[dict[str, Any]] = []
        for bundle_path, source in sources.items():
            destination = temporary_root / bundle_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            descriptors.append(_artifact_descriptor(temporary_root, bundle_path))
            source_map[bundle_path] = source.relative_to(root).as_posix()

        plan_path = temporary_root / CORE_EVIDENCE_PLAN
        _write_canonical_json(plan_path, dict(verification_plan))
        descriptors.append(_artifact_descriptor(temporary_root, CORE_EVIDENCE_PLAN))

        source_map_path = temporary_root / CORE_EVIDENCE_SOURCE_MAP
        _write_canonical_json(source_map_path, {"schemaVersion": SCHEMA_VERSION, "sources": source_map})
        descriptors.append(_artifact_descriptor(temporary_root, CORE_EVIDENCE_SOURCE_MAP))

        manifest = {
            "schemaVersion": SCHEMA_VERSION,
            "artifacts": descriptors,
            "baselineCommit": baseline_commit,
            "process": "proofloop-core",
            "sealedAt": time.time(),
        }
        if bundle_root.exists():
            shutil.rmtree(bundle_root)
        temporary_root.replace(bundle_root)
        _write_canonical_json(root / CORE_EVIDENCE_MANIFEST, manifest)
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise

    return validate_core_evidence(root)


def validate_core_evidence(run_dir: Path) -> dict[str, Any]:
    """Revalidate a Core-sealed bundle, including freshness of source files."""
    root = Path(run_dir).resolve()
    manifest_path = root / CORE_EVIDENCE_MANIFEST
    bundle_root = root / CORE_EVIDENCE_DIR
    if not manifest_path.is_file():
        return _core_rejected(CORE_EVIDENCE_MISSING)
    try:
        manifest = _read_json_object(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return _core_rejected(CORE_EVIDENCE_MISSING)

    structural = validate_bundle(bundle_root, manifest)
    if structural.status != "STRUCTURALLY_VALID":
        return _core_rejected(*structural.reasons)

    try:
        source_map = _read_json_object(bundle_root / CORE_EVIDENCE_SOURCE_MAP)
        plan = _read_json_object(bundle_root / CORE_EVIDENCE_PLAN)
        checks = _read_json_object(bundle_root / "checks.json")
        diff = _read_json_object(bundle_root / "diff-guard.json")
    except (OSError, ValueError, json.JSONDecodeError):
        return _core_rejected(CORE_EVIDENCE_SEMANTIC_INVALID, candidate_digest=structural.candidate_digest)

    if _verification_plan_digest(plan) != plan.get("planSha256"):
        return _core_rejected(CORE_EVIDENCE_PLAN_MISMATCH, candidate_digest=structural.candidate_digest)
    if not _sources_match(root, bundle_root, source_map):
        return _core_rejected(CORE_EVIDENCE_SOURCE_MISMATCH, candidate_digest=structural.candidate_digest)
    if not _mandatory_checks_passed(plan, checks):
        return _core_rejected(CORE_EVIDENCE_MANDATORY_CHECK_MISSING, candidate_digest=structural.candidate_digest)
    if not _evaluator_inputs_match(plan, checks):
        return _core_rejected(CORE_EVIDENCE_EVALUATOR_CHANGED, candidate_digest=structural.candidate_digest)
    if diff.get("verdict") not in {"PASS", "FAIL"} or checks.get("verdict") not in {"PASS", "FAIL"}:
        return _core_rejected(CORE_EVIDENCE_SEMANTIC_INVALID, candidate_digest=structural.candidate_digest)
    return {
        "status": "VALID",
        "reasons": [],
        "candidateDigest": structural.candidate_digest,
        "checks": checks,
        "diff": diff,
        "verificationPlanSha256": plan["planSha256"],
    }


# ---------------------------------------------------------------------------
# Stage 1: manifest schema validation
# ---------------------------------------------------------------------------

def _validate_manifest_schema(
    manifest: Mapping[str, Any], reasons: list[str],
) -> None:
    if not isinstance(manifest, Mapping):
        reasons.append(REJECTED_SCHEMA_VIOLATION)
        return

    keys = set(manifest.keys())
    if not _MANIFEST_REQUIRED_KEYS.issubset(keys):
        reasons.append(REJECTED_SCHEMA_VIOLATION)
        return
    if keys - _MANIFEST_ALLOWED_KEYS:
        reasons.append(REJECTED_SCHEMA_VIOLATION)
        return
    if manifest.get("schemaVersion") != SCHEMA_VERSION:
        reasons.append(REJECTED_SCHEMA_VIOLATION)
        return

    arts = manifest.get("artifacts")
    if not isinstance(arts, (list, tuple)):
        reasons.append(REJECTED_SCHEMA_VIOLATION)
        return

    for entry in arts:
        if not isinstance(entry, Mapping):
            reasons.append(REJECTED_SCHEMA_VIOLATION)
            return
        entry_keys = set(entry.keys())
        if not _ARTIFACT_REQUIRED_KEYS.issubset(entry_keys):
            reasons.append(REJECTED_SCHEMA_VIOLATION)
            return
        if entry_keys - _ARTIFACT_ALLOWED_KEYS:
            reasons.append(REJECTED_SCHEMA_VIOLATION)
            return
        if not isinstance(entry.get("path"), str) or not entry["path"]:
            reasons.append(REJECTED_SCHEMA_VIOLATION)
            return
        sha = entry.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64:
            reasons.append(REJECTED_SCHEMA_VIOLATION)
            return
        size = entry.get("sizeBytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            reasons.append(REJECTED_SCHEMA_VIOLATION)
            return


# ---------------------------------------------------------------------------
# Stage 2: path security and collision
# ---------------------------------------------------------------------------

def _validate_paths(
    artifacts: Sequence[Mapping[str, Any]], reasons: list[str],
) -> None:
    seen_raw: set[str] = set()
    seen_nfc: set[str] = set()
    seen_casefold: set[str] = set()

    for entry in artifacts:
        path_str = entry["path"]

        # Empty path
        if not path_str.strip():
            reasons.append(REJECTED_PATH_SECURITY_VIOLATION)
            return

        # Absolute path
        if path_str.startswith("/") or path_str.startswith("\\"):
            reasons.append(REJECTED_PATH_SECURITY_VIOLATION)
            return

        # Windows absolute (e.g. C:\...)
        if len(path_str) >= 2 and path_str[1] == ":":
            reasons.append(REJECTED_PATH_SECURITY_VIOLATION)
            return

        # Parent traversal
        parts = PurePosixPath(path_str).parts
        if ".." in parts:
            reasons.append(REJECTED_PATH_SECURITY_VIOLATION)
            return

        # Duplicate (exact)
        if path_str in seen_raw:
            reasons.append(REJECTED_PATH_COLLISION)
            return
        seen_raw.add(path_str)

        # NFC collision
        nfc = unicodedata.normalize("NFC", path_str)
        if nfc in seen_nfc and path_str not in seen_raw - {path_str}:
            # Already have a different raw that normalizes to same NFC
            pass  # Caught by casefold below or exact above
        if nfc != path_str:
            # The path itself isn't NFC — check if the NFC form is already seen
            if nfc in seen_raw:
                reasons.append(REJECTED_PATH_COLLISION)
                return
        if nfc in seen_nfc:
            reasons.append(REJECTED_PATH_COLLISION)
            return
        seen_nfc.add(nfc)

        # Case-fold collision
        folded = path_str.casefold()
        if folded in seen_casefold:
            reasons.append(REJECTED_PATH_COLLISION)
            return
        seen_casefold.add(folded)


# ---------------------------------------------------------------------------
# Stage 3: bundle tree enumeration
# ---------------------------------------------------------------------------

def _validate_tree(
    bundle_root: Path, declared_paths: set[str], reasons: list[str],
) -> None:
    if not bundle_root.is_dir():
        reasons.append(REJECTED_MISSING_ARTIFACT)
        return

    actual_files: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(bundle_root):
        for filename in filenames:
            full = Path(dirpath) / filename
            rel = full.relative_to(bundle_root).as_posix()
            actual_files.add(rel)

    missing = declared_paths - actual_files
    unexpected = actual_files - declared_paths

    if missing:
        reasons.append(REJECTED_MISSING_ARTIFACT)
    if unexpected:
        reasons.append(REJECTED_UNEXPECTED_ARTIFACT)


# ---------------------------------------------------------------------------
# Stages 4-6: per-file validation
# ---------------------------------------------------------------------------

def _validate_file(
    file_path: Path,
    descriptor: Mapping[str, Any],
) -> tuple[list[str], int, str]:
    """Validate a single file. Returns (reasons, actual_size, actual_hash)."""
    reasons: list[str] = []

    # Stage 4 — file type: must be regular, not symlink/hardlink
    try:
        # Try O_NOFOLLOW where available
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(str(file_path), flags)
    except OSError:
        reasons.append(REJECTED_FILE_TYPE_VIOLATION)
        return reasons, 0, ""

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            reasons.append(REJECTED_FILE_TYPE_VIOLATION)
            return reasons, 0, ""
        # Hardlink detection: nlink > 1
        if st.st_nlink > 1:
            reasons.append(REJECTED_FILE_TYPE_VIOLATION)
            return reasons, 0, ""

        # Pre-open lstat for symlink check (belt-and-suspenders)
        try:
            lst = os.lstat(str(file_path))
            if stat.S_ISLNK(lst.st_mode):
                reasons.append(REJECTED_FILE_TYPE_VIOLATION)
                return reasons, 0, ""
            # inode/device match
            if lst.st_ino != st.st_ino or lst.st_dev != st.st_dev:
                reasons.append(REJECTED_FILE_TYPE_VIOLATION)
                return reasons, 0, ""
        except OSError:
            reasons.append(REJECTED_FILE_TYPE_VIOLATION)
            return reasons, 0, ""

        # Stage 5 — bounded hash and size computation
        hasher = hashlib.sha256()
        actual_size = 0
        with os.fdopen(os.dup(fd), "rb") as f:
            while True:
                chunk = f.read(_READ_CHUNK)
                if not chunk:
                    break
                hasher.update(chunk)
                actual_size += len(chunk)

        actual_hash = hasher.hexdigest()

        # Size check
        expected_size = descriptor["sizeBytes"]
        if actual_size != expected_size:
            reasons.append(REJECTED_SIZE_MISMATCH)

        # Hash check
        expected_hash = descriptor["sha256"].lower()
        if actual_hash != expected_hash:
            reasons.append(REJECTED_HASH_MISMATCH)

        # Stage 6 — JSON/JSONL syntax verification
        path_str = descriptor["path"]
        if path_str.endswith(".json"):
            _verify_json(file_path, reasons)
        elif path_str.endswith(".jsonl"):
            _verify_jsonl(file_path, reasons)

    finally:
        os.close(fd)

    return reasons, actual_size, actual_hash


def _verify_json(file_path: Path, reasons: list[str]) -> None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        reasons.append(REJECTED_MALFORMED_JSON)


def _verify_jsonl(file_path: Path, reasons: list[str]) -> None:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    json.loads(stripped)
    except (json.JSONDecodeError, UnicodeDecodeError):
        reasons.append(REJECTED_MALFORMED_JSONL)


# ---------------------------------------------------------------------------
# Stage 7: canonical candidate digest
# ---------------------------------------------------------------------------

def _compute_candidate_digest(entries: list[dict[str, Any]]) -> str:
    """Compute canonical digest from re-verified artifact metadata.

    Self-claim fields (verdict, evidenceLevel, bundleHash) are excluded
    because they come from the candidate, not the validator.
    """
    canonical = sorted(entries, key=lambda e: e["path"])
    payload = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _artifact_descriptor(bundle_root: Path, relative_path: str) -> dict[str, Any]:
    path = bundle_root / relative_path
    return {
        "path": relative_path,
        "sha256": _sha256_file(path),
        "sizeBytes": path.stat().st_size,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_canonical_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _require_json_matches(path: Path, expected: Mapping[str, Any]) -> None:
    if not path.is_file():
        raise LiveEvidenceValidationError(f"Core artifact is missing: {path}")
    try:
        actual = _read_json_object(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise LiveEvidenceValidationError(f"Core artifact is invalid JSON: {path}") from exc
    if _canonical_json(actual) != _canonical_json(expected):
        raise LiveEvidenceValidationError(f"Core artifact changed before sealing: {path}")


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _verification_plan_digest(plan: Mapping[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("planSha256", None)
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sources_match(root: Path, bundle_root: Path, source_map: Mapping[str, Any]) -> bool:
    if source_map.get("schemaVersion") != SCHEMA_VERSION or not isinstance(source_map.get("sources"), Mapping):
        return False
    for bundle_path, source_path in source_map["sources"].items():
        if not isinstance(bundle_path, str) or not isinstance(source_path, str):
            return False
        if not _is_safe_relative_path(bundle_path) or not _is_safe_relative_path(source_path):
            return False
        captured = bundle_root / bundle_path
        source = (root / source_path).resolve()
        if not captured.is_file() or not source.is_file():
            return False
        if source != root and root not in source.parents:
            return False
        if _sha256_file(captured) != _sha256_file(source):
            return False
    return True


def _is_safe_relative_path(path: str) -> bool:
    if not path or path.startswith(("/", "\\")) or (len(path) >= 2 and path[1] == ":"):
        return False
    return ".." not in PurePosixPath(path).parts


def _mandatory_checks_passed(plan: Mapping[str, Any], checks: Mapping[str, Any]) -> bool:
    mandatory = plan.get("mandatoryChecks")
    results = checks.get("checks")
    if not isinstance(mandatory, list) or not mandatory or not isinstance(results, list):
        return False
    passed_commands = {
        _command_digest(item.get("command"))
        for item in results
        if isinstance(item, Mapping) and item.get("status") == "PASS" and isinstance(item.get("command"), list)
    }
    required_commands = {
        item.get("commandSha256")
        for item in mandatory
        if isinstance(item, Mapping) and item.get("mandatory") is True and isinstance(item.get("commandSha256"), str)
    }
    return bool(required_commands) and required_commands.issubset(passed_commands)


def _evaluator_inputs_match(plan: Mapping[str, Any], checks: Mapping[str, Any]) -> bool:
    inputs = plan.get("evaluatorInputs")
    if not isinstance(inputs, list):
        return False
    if not inputs:
        return True
    repository = checks.get("repository")
    if not isinstance(repository, str) or not repository:
        return False
    root = Path(repository).resolve()
    for entry in inputs:
        if not isinstance(entry, Mapping):
            return False
        relative = entry.get("path")
        expected_hash = entry.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str) or not _is_safe_relative_path(relative):
            return False
        current = (root / relative).resolve()
        if not current.is_file() or (current != root and root not in current.parents):
            return False
        if _sha256_file(current) != expected_hash:
            return False
    return True


def _command_digest(command: Any) -> str:
    if not isinstance(command, list) or not command:
        return ""
    parts = [str(part) for part in command]
    executable = Path(parts[0]).name.casefold()
    if executable.startswith("python"):
        parts[0] = "<python>"
    return hashlib.sha256(
        json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _core_rejected(*reasons: str, candidate_digest: str | None = None) -> dict[str, Any]:
    return {
        "status": "REJECTED",
        "reasons": sorted(set(reasons)),
        "candidateDigest": candidate_digest,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rejected(reasons: list[str]) -> ValidationResult:
    return ValidationResult(
        status="REJECTED",
        reasons=tuple(sorted(set(reasons))),
        candidate_digest=None,
    )
