from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from proofloop_core.usage import TokenLedger, UsageObservation, normalize_tokens


class UsageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root))

    def test_normalizes_provider_token_aliases(self) -> None:
        self.assertEqual(
            {"input": 10, "output": 3, "cacheRead": 7, "reasoning": 2},
            normalize_tokens(
                {
                    "input_tokens": 10,
                    "output_tokens": 3,
                    "cache_read_input_tokens": 7,
                    "reasoning_output_tokens": 2,
                }
            ),
        )

    def test_ledger_deduplicates_and_aggregates_cumulative_usage(self) -> None:
        ledger = TokenLedger(self.root)
        for input_tokens in (10, 15, 15):
            ledger.record(
                UsageObservation(
                    run_id="run-1",
                    invocation_id="01-codex-explorer_fast",
                    role="explorer_fast",
                    runtime="codex",
                    model="gpt-test",
                    tokens={"input": input_tokens, "output": 2},
                    source="acp",
                    measurement_kind="cumulative",
                    session_id="session-1",
                    source_event_id=f"usage-{input_tokens}",
                )
            )

        summary = ledger.summarize([{"invocationId": "01-codex-explorer_fast"}])

        self.assertEqual(2, len(ledger.observations()))
        self.assertEqual(15, summary["totals"]["input"])
        self.assertEqual(2, summary["totals"]["output"])
        self.assertEqual(1.0, summary["coverage"]["tokenCoverageRatio"])
        self.assertEqual("gpt-test", summary["byModel"][0]["model"])

    def test_unmeasured_invocation_is_not_reported_as_zero_usage(self) -> None:
        summary = TokenLedger(self.root).summarize([{"invocationId": "missing"}])

        self.assertEqual(0, summary["coverage"]["measuredInvocations"])
        self.assertEqual(1, summary["coverage"]["expectedInvocations"])
        self.assertEqual([], summary["byInvocation"])


if __name__ == "__main__":
    unittest.main()
