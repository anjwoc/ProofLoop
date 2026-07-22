from __future__ import annotations

import hashlib
import unittest

from proofloop_core.engine.intent import compile_intent


class IntentContractTest(unittest.TestCase):
    def test_preserves_original_request_and_derives_stable_hash(self) -> None:
        request = "API 캐시를 추가해줘.\n- 기존 응답 형식을 유지한다\n- 전체 테스트를 통과한다"

        contract = compile_intent(request)

        self.assertEqual(request, contract.original_request)
        self.assertEqual(hashlib.sha256(request.encode("utf-8")).hexdigest(), contract.original_request_hash)
        self.assertEqual(contract.to_dict(), compile_intent(request).to_dict())
        self.assertGreaterEqual(len(contract.acceptance_criteria), 2)

    def test_does_not_invent_authorization_or_hide_unknowns(self) -> None:
        contract = compile_intent("필요하면 배포 설정도 적당히 고쳐서 로그인 버그를 수정해줘")

        self.assertIn("repository files required by the accepted objective", contract.authorization_boundary)
        self.assertNotIn("production deployment", contract.authorization_boundary)
        self.assertTrue(contract.unknowns)
        self.assertIn("auth", contract.risk_signals)

    def test_rejects_empty_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty"):
            compile_intent("  ")


if __name__ == "__main__":
    unittest.main()
