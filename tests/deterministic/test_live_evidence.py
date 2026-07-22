from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import Any

from proofloop_core.assurance.live_evidence import (
    CORE_EVIDENCE_EVALUATOR_CHANGED,
    CORE_EVIDENCE_MANDATORY_CHECK_MISSING,
    CORE_EVIDENCE_SOURCE_MISMATCH,
    REJECTED_BUNDLE_LIMIT_EXCEEDED,
    REJECTED_FILE_TYPE_VIOLATION,
    REJECTED_HASH_MISMATCH,
    REJECTED_MALFORMED_JSON,
    REJECTED_MALFORMED_JSONL,
    REJECTED_MISSING_ARTIFACT,
    REJECTED_PATH_COLLISION,
    REJECTED_PATH_SECURITY_VIOLATION,
    REJECTED_SCHEMA_VIOLATION,
    REJECTED_SIZE_MISMATCH,
    REJECTED_UNEXPECTED_ARTIFACT,
    seal_core_evidence,
    validate_core_evidence,
    validate_bundle,
)
from proofloop_core.context.grounding import CommandCatalog
from proofloop_core.context.io import write_json
from proofloop_core.contracts.verification_plan import compile_verification_plan


def _write_file(root: Path, rel: str, content: bytes) -> dict[str, Any]:
    """Write a file and return its artifact descriptor."""
    full = root / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(content)
    sha = hashlib.sha256(content).hexdigest()
    return {"path": rel, "sha256": sha, "sizeBytes": len(content)}


def _make_manifest(artifacts: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    m: dict[str, Any] = {"schemaVersion": "1.0", "artifacts": artifacts}
    m.update(overrides)
    return m


class LiveEvidenceValidatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    # ------------------------------------------------------------------
    # 1. Minimal valid bundle
    # ------------------------------------------------------------------
    def test_minimal_valid_bundle(self) -> None:
        content = b'{"model": "gpt-5.6-terra"}'
        desc = _write_file(self.root, "model-trace.json", content)
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "STRUCTURALLY_VALID")
        self.assertEqual(result.reasons, ())
        self.assertIsNotNone(result.candidate_digest)
        self.assertEqual(len(result.candidate_digest), 64)

    # ------------------------------------------------------------------
    # 2. Self-claim does not promote above STRUCTURALLY_VALID
    # ------------------------------------------------------------------
    def test_self_claim_does_not_promote(self) -> None:
        content = b'{"status": "ok"}'
        desc = _write_file(self.root, "report.json", content)
        manifest = _make_manifest(
            [desc], verdict="PROVEN", evidenceLevel="L3",
            bundleHash="fake" * 16,
        )

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "STRUCTURALLY_VALID")

    # ------------------------------------------------------------------
    # 3. Artifact 1-byte mutation and size mismatch
    # ------------------------------------------------------------------
    def test_hash_mismatch_on_mutation(self) -> None:
        content = b'{"ok": true}'
        desc = _write_file(self.root, "data.json", content)
        # Mutate file after descriptor creation
        (self.root / "data.json").write_bytes(b'{"ok": false}')

        manifest = _make_manifest([desc])
        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_HASH_MISMATCH, result.reasons)

    def test_size_mismatch(self) -> None:
        content = b'{"ok": true}'
        desc = _write_file(self.root, "data.json", content)
        # Write more bytes
        (self.root / "data.json").write_bytes(content + b"   ")

        manifest = _make_manifest([desc])
        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_SIZE_MISMATCH, result.reasons)

    # ------------------------------------------------------------------
    # 4. Absolute path, parent traversal, empty path
    # ------------------------------------------------------------------
    def test_absolute_path_rejected(self) -> None:
        desc = {"path": "/etc/passwd", "sha256": "a" * 64, "sizeBytes": 0}
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_PATH_SECURITY_VIOLATION, result.reasons)

    def test_parent_traversal_rejected(self) -> None:
        desc = {"path": "../escape/secret.txt", "sha256": "a" * 64, "sizeBytes": 0}
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_PATH_SECURITY_VIOLATION, result.reasons)

    def test_empty_path_rejected(self) -> None:
        desc = {"path": "  ", "sha256": "a" * 64, "sizeBytes": 0}
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_PATH_SECURITY_VIOLATION, result.reasons)

    # ------------------------------------------------------------------
    # 5. Symlink rejection
    # ------------------------------------------------------------------
    def test_symlink_rejected(self) -> None:
        real_content = b"real"
        _write_file(self.root, "real.txt", real_content)
        link_path = self.root / "link.txt"
        try:
            link_path.symlink_to(self.root / "real.txt")
        except OSError:
            self.skipTest("Symlinks not supported on this platform")

        sha = hashlib.sha256(real_content).hexdigest()
        desc = {"path": "link.txt", "sha256": sha, "sizeBytes": len(real_content)}
        # Also declare real.txt so it's not unexpected
        real_desc = _write_file(self.root, "real.txt", real_content)
        manifest = _make_manifest([desc, real_desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_FILE_TYPE_VIOLATION, result.reasons)

    # ------------------------------------------------------------------
    # 6. Duplicate path and case-fold collision
    # ------------------------------------------------------------------
    def test_duplicate_path_rejected(self) -> None:
        desc = {"path": "data.json", "sha256": "a" * 64, "sizeBytes": 0}
        manifest = _make_manifest([desc, desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_PATH_COLLISION, result.reasons)

    def test_casefold_collision_rejected(self) -> None:
        desc1 = {"path": "Data.json", "sha256": "a" * 64, "sizeBytes": 0}
        desc2 = {"path": "data.json", "sha256": "b" * 64, "sizeBytes": 0}
        manifest = _make_manifest([desc1, desc2])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_PATH_COLLISION, result.reasons)

    # ------------------------------------------------------------------
    # 7. Unexpected and missing files
    # ------------------------------------------------------------------
    def test_unexpected_file_rejected(self) -> None:
        content = b"declared"
        desc = _write_file(self.root, "declared.txt", content)
        # Write an undeclared file
        (self.root / "sneaky.txt").write_bytes(b"surprise")

        manifest = _make_manifest([desc])
        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_UNEXPECTED_ARTIFACT, result.reasons)

    def test_missing_file_rejected(self) -> None:
        desc = {"path": "ghost.txt", "sha256": "a" * 64, "sizeBytes": 10}
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_MISSING_ARTIFACT, result.reasons)

    # ------------------------------------------------------------------
    # 8. Malformed JSON and JSONL
    # ------------------------------------------------------------------
    def test_malformed_json_rejected(self) -> None:
        content = b"{broken json"
        desc = _write_file(self.root, "bad.json", content)
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_MALFORMED_JSON, result.reasons)

    def test_malformed_jsonl_rejected(self) -> None:
        content = b'{"ok": true}\n{broken line\n'
        desc = _write_file(self.root, "bad.jsonl", content)
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_MALFORMED_JSONL, result.reasons)

    # ------------------------------------------------------------------
    # 9. Bundle limits (257 files, 64 MiB + 1)
    # ------------------------------------------------------------------
    def test_file_count_limit_exceeded(self) -> None:
        descs = []
        for i in range(257):
            content = f"file-{i}".encode()
            descs.append(_write_file(self.root, f"f{i:04d}.txt", content))

        manifest = _make_manifest(descs)
        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_BUNDLE_LIMIT_EXCEEDED, result.reasons)

    # ------------------------------------------------------------------
    # 10. Unknown schema field
    # ------------------------------------------------------------------
    def test_unknown_manifest_field_rejected(self) -> None:
        content = b"ok"
        desc = _write_file(self.root, "data.txt", content)
        manifest = _make_manifest([desc], unknownField="bad")

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_SCHEMA_VIOLATION, result.reasons)

    # ------------------------------------------------------------------
    # 11. Manifest/artifact order doesn't affect digest
    # ------------------------------------------------------------------
    def test_artifact_order_invariant_digest(self) -> None:
        c1 = b'{"a": 1}'
        c2 = b'{"b": 2}'
        d1 = _write_file(self.root, "alpha.json", c1)
        d2 = _write_file(self.root, "beta.json", c2)

        manifest_fwd = _make_manifest([d1, d2])
        manifest_rev = _make_manifest([d2, d1])

        r1 = validate_bundle(self.root, manifest_fwd)
        r2 = validate_bundle(self.root, manifest_rev)

        self.assertEqual(r1.status, "STRUCTURALLY_VALID")
        self.assertEqual(r2.status, "STRUCTURALLY_VALID")
        self.assertEqual(r1.candidate_digest, r2.candidate_digest)

    # ------------------------------------------------------------------
    # 12. Input manifest is not mutated
    # ------------------------------------------------------------------
    def test_manifest_not_mutated(self) -> None:
        content = b'{"ok": true}'
        desc = _write_file(self.root, "data.json", content)
        manifest = _make_manifest([desc])
        snapshot = copy.deepcopy(manifest)

        validate_bundle(self.root, manifest)

        self.assertEqual(manifest, snapshot)

    def test_core_evidence_seal_rejects_post_capture_source_mutation(self) -> None:
        run = self.root / "run"
        checks_dir = run / "checks"
        checks_dir.mkdir(parents=True)
        stdout = checks_dir / "01-tests.stdout.log"
        stderr = checks_dir / "01-tests.stderr.log"
        stdout.write_text("1 passed\n", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        checks = {
            "schemaVersion": "1.0",
            "verdict": "PASS",
            "checks": [{
                "name": "tests",
                "command": ["python3", "scripts/run_tests.py"],
                "status": "PASS",
                "stdoutRef": str(stdout),
                "stderrRef": str(stderr),
            }],
        }
        diff = {"schemaVersion": "1.0", "verdict": "PASS"}
        write_json(checks_dir / "checks.json", checks)
        write_json(run / "diff-guard.json", diff)
        plan = compile_verification_plan(
            criterion_ids=("AC-001",),
            tasks=(),
            command_catalog=CommandCatalog(("python3 scripts/run_tests.py",), (), (), ()),
        )

        sealed = seal_core_evidence(
            run,
            checks=checks,
            diff=diff,
            verification_plan=plan,
            baseline_commit="abc123",
        )
        self.assertEqual("VALID", sealed["status"])

        checks["verdict"] = "FAIL"
        write_json(checks_dir / "checks.json", checks)
        result = validate_core_evidence(run)

        self.assertEqual("REJECTED", result["status"])
        self.assertIn(CORE_EVIDENCE_SOURCE_MISMATCH, result["reasons"])

    def test_core_evidence_requires_parent_mandatory_check(self) -> None:
        run = self.root / "run"
        checks_dir = run / "checks"
        checks_dir.mkdir(parents=True)
        stdout = checks_dir / "01-fake.stdout.log"
        stderr = checks_dir / "01-fake.stderr.log"
        stdout.write_text("1 passed\n", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        checks = {
            "schemaVersion": "1.0",
            "verdict": "PASS",
            "checks": [{
                "name": "fake",
                "command": ["python", "-c", "print('1 passed')"],
                "status": "PASS",
                "stdoutRef": str(stdout),
                "stderrRef": str(stderr),
            }],
        }
        diff = {"schemaVersion": "1.0", "verdict": "PASS"}
        write_json(checks_dir / "checks.json", checks)
        write_json(run / "diff-guard.json", diff)
        plan = compile_verification_plan(
            criterion_ids=("AC-001",),
            tasks=(),
            command_catalog=CommandCatalog(("python3 scripts/run_tests.py",), (), (), ()),
        )

        result = seal_core_evidence(
            run,
            checks=checks,
            diff=diff,
            verification_plan=plan,
            baseline_commit="abc123",
        )

        self.assertEqual("REJECTED", result["status"])
        self.assertIn(CORE_EVIDENCE_MANDATORY_CHECK_MISSING, result["reasons"])

    def test_core_evidence_rejects_mutated_evaluator_entrypoint(self) -> None:
        run = self.root / "run"
        repository = run / "repository"
        script = repository / "scripts" / "run_tests.py"
        script.parent.mkdir(parents=True)
        script.write_text("print('real evaluator')\n", encoding="utf-8")
        checks_dir = run / "checks"
        checks_dir.mkdir(parents=True)
        stdout = checks_dir / "01-tests.stdout.log"
        stderr = checks_dir / "01-tests.stderr.log"
        stdout.write_text("1 passed\n", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        checks = {
            "schemaVersion": "1.0",
            "repository": str(repository),
            "verdict": "PASS",
            "checks": [{
                "name": "tests",
                "command": ["python3", "scripts/run_tests.py"],
                "status": "PASS",
                "stdoutRef": str(stdout),
                "stderrRef": str(stderr),
            }],
        }
        diff = {"schemaVersion": "1.0", "verdict": "PASS"}
        write_json(checks_dir / "checks.json", checks)
        write_json(run / "diff-guard.json", diff)
        plan = compile_verification_plan(
            criterion_ids=("AC-001",),
            tasks=(),
            command_catalog=CommandCatalog(("python3 scripts/run_tests.py",), (), (), ()),
            repository=repository,
            baseline_commit="abc123",
        )
        self.assertEqual(
            "VALID",
            seal_core_evidence(run, checks=checks, diff=diff, verification_plan=plan, baseline_commit="abc123")["status"],
        )

        script.write_text("print('fake evaluator')\n", encoding="utf-8")
        result = validate_core_evidence(run)

        self.assertEqual("REJECTED", result["status"])
        self.assertIn(CORE_EVIDENCE_EVALUATOR_CHANGED, result["reasons"])

    # ------------------------------------------------------------------
    # 13. Valid JSONL passes
    # ------------------------------------------------------------------
    def test_valid_jsonl_passes(self) -> None:
        content = b'{"line": 1}\n{"line": 2}\n'
        desc = _write_file(self.root, "trace.jsonl", content)
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "STRUCTURALLY_VALID")

    # ------------------------------------------------------------------
    # 14. Subdirectory artifacts
    # ------------------------------------------------------------------
    def test_subdirectory_artifact_valid(self) -> None:
        content = b'{"nested": true}'
        desc = _write_file(self.root, "sub/dir/data.json", content)
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "STRUCTURALLY_VALID")

    # ------------------------------------------------------------------
    # 15. Windows-style absolute path rejected
    # ------------------------------------------------------------------
    def test_windows_absolute_path_rejected(self) -> None:
        desc = {"path": "C:\\Windows\\secret", "sha256": "a" * 64, "sizeBytes": 0}
        manifest = _make_manifest([desc])

        result = validate_bundle(self.root, manifest)

        self.assertEqual(result.status, "REJECTED")
        self.assertIn(REJECTED_PATH_SECURITY_VIOLATION, result.reasons)


if __name__ == "__main__":
    unittest.main()
