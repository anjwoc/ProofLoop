from __future__ import annotations

import dataclasses
import hashlib
import unittest

from proofloop_core.request_envelope import create


class RequestEnvelopeTest(unittest.TestCase):
    def test_preserves_exact_raw_text_without_stripping(self) -> None:
        text = "  결제 재시도 중복 방지\n"
        env = create(request_id="pl-1", raw_text=text, repo_root="/repo", invocation_source="codex")
        self.assertEqual(text, env.raw_text)

    def test_hash_is_sha256_of_exact_bytes(self) -> None:
        text = "implement idempotent retries"
        env = create(request_id="pl-1", raw_text=text, repo_root="/repo", invocation_source="codex")
        expected = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(expected, env.raw_hash)

    def test_whitespace_variants_hash_differently(self) -> None:
        base = create(request_id="a", raw_text="do x", repo_root="/r", invocation_source="cli").raw_hash
        padded = create(request_id="b", raw_text="do x ", repo_root="/r", invocation_source="cli").raw_hash
        self.assertNotEqual(base, padded)

    def test_empty_or_whitespace_only_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create(request_id="a", raw_text="   \n", repo_root="/r", invocation_source="cli")

    def test_envelope_is_immutable(self) -> None:
        env = create(request_id="a", raw_text="do x", repo_root="/r", invocation_source="cli")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            env.raw_text = "tampered"  # type: ignore[misc]

    def test_explicit_authority_fields_preserved_as_tuples(self) -> None:
        env = create(
            request_id="a",
            raw_text="do x",
            repo_root="/r",
            invocation_source="cli",
            explicit_permissions=["repository_mutation"],
            explicit_denials=["git_remote"],
            user_constraints=["do not touch docs/"],
        )
        self.assertEqual(("repository_mutation",), env.explicit_permissions)
        self.assertEqual(("git_remote",), env.explicit_denials)
        self.assertEqual(("do not touch docs/",), env.user_constraints)

    def test_to_dict_has_schema_and_camel_case_fields(self) -> None:
        env = create(request_id="pl-1", raw_text="do x", repo_root="/repo", host_requested="codex", invocation_source="codex")
        data = env.to_dict()
        self.assertEqual("1.0", data["schemaVersion"])
        self.assertEqual("pl-1", data["requestId"])
        self.assertEqual("do x", data["rawText"])
        self.assertTrue(data["rawHash"].startswith("sha256:"))
        self.assertEqual("codex", data["hostRequested"])
        self.assertEqual("codex", data["invocationSource"])
        self.assertIn("receivedAt", data)
        self.assertEqual([], data["explicitPermissions"])


if __name__ == "__main__":
    unittest.main()
