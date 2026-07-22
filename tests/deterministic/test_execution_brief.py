from __future__ import annotations

import copy
import hashlib
import unittest
from typing import Any

from proofloop_core.contracts.execution_brief import (
    ExecutionBriefValidationError,
    ProvenanceType,
    compose_execution_brief,
    validate_execution_brief,
)


def _exact_string_pointers(value: object, target: str, pointer: str = "") -> set[str]:
    if isinstance(value, str):
        return {pointer or "/"} if value == target else set()
    if isinstance(value, dict):
        found: set[str] = set()
        for key, item in value.items():
            escaped = str(key).replace("~", "~0").replace("/", "~1")
            found.update(_exact_string_pointers(item, target, f"{pointer}/{escaped}"))
        return found
    if isinstance(value, list):
        found = set()
        for index, item in enumerate(value):
            found.update(_exact_string_pointers(item, target, f"{pointer}/{index}"))
        return found
    return set()


class ExecutionBriefTest(unittest.TestCase):
    def setUp(self) -> None:
        request = "API 캐시를 추가해줘."
        self.request = {
            "schemaVersion": "1.0",
            "requestId": "REQ-001",
            "rawText": request,
            "rawHash": hashlib.sha256(request.encode("utf-8")).hexdigest(),
            "receivedAt": "2026-07-21T00:00:00Z",
            "repoRoot": "/fake/repo",
            "hostRequested": "cli",
            "explicitPermissions": [],
            "explicitDenials": [],
            "userConstraints": [],
            "invocationSource": "test",
        }
        self.intent = {
            "schemaVersion": "1.0",
            "originalRequest": request,
            "originalRequestHash": hashlib.sha256(request.encode("utf-8")).hexdigest(),
            "objective": request,
            "acceptanceCriteria": [{"id": "AC-001", "statement": request}],
            "constraints": ["기존 응답 형식을 유지한다."],
            "nonGoals": ["외부 배포는 하지 않는다."],
            "authorizationBoundary": "승인된 저장소 범위만 변경한다.",
            "assumptions": [],
            "unknowns": ["캐시 backend 선택은 저장소 근거가 필요하다."],
            "riskSignals": ["data"],
            "targetArtifacts": ["src/cache.py"],
        }
        self.strategy = {"schemaVersion": "1.0", "tier": "T1", "plannerRequired": False}
        self.context = {"status": "SKIPPED", "reason": "FAST_LANE"}
        self.baseline = "0123456789abcdef"

    def compose(
        self,
        *,
        request_artifact: dict[str, Any] | None = None,
        intent_contract: dict[str, Any] | None = None,
        strategy: dict[str, Any] | None = None,
        repository_context: dict[str, Any] | None = None,
        repository_baseline: str | None = None,
    ) -> dict[str, Any]:
        return compose_execution_brief(
            request_artifact=request_artifact if request_artifact is not None else self.request,
            intent_contract=intent_contract if intent_contract is not None else self.intent,
            strategy=strategy if strategy is not None else self.strategy,
            repository_context=repository_context if repository_context is not None else self.context,
            repository_baseline=repository_baseline if repository_baseline is not None else self.baseline,
        )

    def test_hash_is_invariant_to_mapping_key_order(self) -> None:
        reordered_strategy = dict(reversed(list(self.strategy.items())))
        reordered_context = dict(reversed(list(self.context.items())))

        first = self.compose()
        second = self.compose(strategy=reordered_strategy, repository_context=reordered_context)

        self.assertEqual(first["provenance"], second["provenance"])

    def test_provenance_changes_with_each_independent_input(self) -> None:
        original = self.compose()["provenance"]
        revised_intent = copy.deepcopy(self.intent)
        revised_intent["objective"] = "캐시를 최소 변경으로 추가한다."
        revised_strategy = {**self.strategy, "tier": "T2"}
        revised_context = {**self.context, "reason": "NO_INDEX"}

        self.assertNotEqual(original, self.compose(intent_contract=revised_intent)["provenance"])
        self.assertNotEqual(original, self.compose(strategy=revised_strategy)["provenance"])
        self.assertNotEqual(original, self.compose(repository_context=revised_context)["provenance"])
        self.assertNotEqual(original, self.compose(repository_baseline="fedcba9876543210")["provenance"])

        request = "API 응답 캐시를 추가해줘."
        revised_request = {
            "schemaVersion": "1.0",
            "requestId": "REQ-002",
            "rawText": request,
            "rawHash": hashlib.sha256(request.encode("utf-8")).hexdigest(),
            "receivedAt": "2026-07-21T00:00:00Z",
            "repoRoot": "/fake/repo",
            "hostRequested": "cli",
            "explicitPermissions": [],
            "explicitDenials": [],
            "userConstraints": [],
            "invocationSource": "test",
        }
        revised_intent = copy.deepcopy(self.intent)
        revised_intent["originalRequest"] = request
        revised_intent["originalRequestHash"] = hashlib.sha256(request.encode("utf-8")).hexdigest()
        self.assertNotEqual(
            original,
            self.compose(request_artifact=revised_request, intent_contract=revised_intent)["provenance"],
        )

    def test_preserves_legacy_intent_fields_without_raw_request(self) -> None:
        brief = self.compose()

        self.assertEqual(
            brief["acceptanceCriteria"],
            [{**ac, "provenance": ProvenanceType.USER_EXPLICIT.value} for ac in self.intent["acceptanceCriteria"]]
        )
        for field in ("constraints", "nonGoals", "riskSignals", "unknowns"):
            self.assertEqual(
                brief[field],
                [{"statement": s, "provenance": ProvenanceType.USER_EXPLICIT.value} for s in self.intent[field]]
            )
        self.assertEqual(brief["authorizationBoundary"], {"statement": self.intent["authorizationBoundary"], "provenance": ProvenanceType.USER_EXPLICIT.value})
        self.assertEqual(brief["objective"], {"statement": self.request["rawText"], "provenance": ProvenanceType.USER_EXPLICIT.value})
        self.assertEqual(
            brief["acceptanceCriteria"][0],
            {"id": "AC-001", "statement": self.request["rawText"], "provenance": ProvenanceType.USER_EXPLICIT.value},
        )
        for forbidden in ("request", "originalRequest", "rawRequest", "requestText", "transcript"):
            self.assertNotIn(forbidden, brief)
        self.assertEqual(
            _exact_string_pointers(brief, self.request["rawText"]),
            {"/objective/statement", "/acceptanceCriteria/0/statement"},
        )

    def test_skipped_context_does_not_invent_facts_or_authorize_targets(self) -> None:
        brief = self.compose()

        self.assertEqual(brief["facts"], [])
        self.assertEqual(brief["inferences"], [])
        self.assertEqual(brief["scope"]["candidates"], ["src/cache.py"])
        self.assertEqual(brief["scope"]["approvedPaths"], [])
        self.assertEqual(brief["scope"]["protectedPaths"], [])
        self.assertEqual(brief["scope"]["status"], "UNRESOLVED")

    def test_active_execution_brief_can_only_constrain_declared_candidates(self) -> None:
        brief = self.compose()
        brief["kind"] = "EXECUTION_BRIEF"
        brief["scope"] = {
            "candidates": ["src/cache.py"],
            "approvedPaths": ["src/cache.py"],
            "protectedPaths": [],
            "status": "CONSTRAINED",
        }
        brief["provenance"]["briefSha256"] = self._rehash(brief)
        validate_execution_brief(brief)

        brief["scope"]["approvedPaths"] = ["src/cache.py", "outside.py"]
        brief["provenance"]["briefSha256"] = self._rehash(brief)
        with self.assertRaisesRegex(ExecutionBriefValidationError, "outside candidates"):
            validate_execution_brief(brief)

    @staticmethod
    def _rehash(brief: dict[str, Any]) -> str:
        from proofloop_core.contracts.execution_brief import _brief_sha256
        return _brief_sha256(brief)

    def test_grounded_items_require_source_references(self) -> None:
        for field in ("facts", "inferences"):
            with self.subTest(field=field):
                brief = self.compose()
                brief[field] = [{"id": "ITEM-001", "statement": "근거 없는 주장", "sourceRefs": []}]
                with self.assertRaisesRegex(ExecutionBriefValidationError, "sourceRefs"):
                    validate_execution_brief(brief)

    def test_open_questions_remain_blocking(self) -> None:
        brief = self.compose()
        self.assertTrue(brief["openQuestions"][0]["blocking"])
        brief["openQuestions"][0]["blocking"] = False
        with self.assertRaisesRegex(ExecutionBriefValidationError, "cannot be downgraded"):
            validate_execution_brief(brief)

    def test_wrong_schema_and_unknown_fields_fail_closed(self) -> None:
        bad_request = {**self.request, "unknown": True}
        with self.assertRaisesRegex(ExecutionBriefValidationError, "unknown"):
            self.compose(request_artifact=bad_request)

        bad_intent = {**self.intent, "schemaVersion": "2.0"}
        with self.assertRaisesRegex(ExecutionBriefValidationError, "schemaVersion"):
            self.compose(intent_contract=bad_intent)

        brief = self.compose()
        brief["unexpected"] = True
        with self.assertRaisesRegex(ExecutionBriefValidationError, "unknown"):
            validate_execution_brief(brief)

    def test_brief_hash_detects_content_tampering_and_malformed_digests(self) -> None:
        brief = self.compose()
        brief["objective"]["statement"] = "변조된 목적"
        with self.assertRaisesRegex(ExecutionBriefValidationError, "briefSha256 does not match"):
            validate_execution_brief(brief)

        brief = self.compose()
        brief["provenance"]["strategySha256"] = "A" * 64
        with self.assertRaisesRegex(ExecutionBriefValidationError, "lowercase SHA-256"):
            validate_execution_brief(brief)

    def test_rejects_request_intent_mismatch_and_floats(self) -> None:
        bad_intent = {**self.intent, "originalRequest": "다른 요청"}
        with self.assertRaisesRegex(ExecutionBriefValidationError, "does not match"):
            self.compose(intent_contract=bad_intent)
        with self.assertRaisesRegex(ExecutionBriefValidationError, "floats"):
            self.compose(strategy={**self.strategy, "score": 0.5})

    def test_inputs_are_not_mutated(self) -> None:
        snapshots = copy.deepcopy((self.request, self.intent, self.strategy, self.context))

        self.compose()

        self.assertEqual(snapshots, (self.request, self.intent, self.strategy, self.context))


if __name__ == "__main__":
    unittest.main()
