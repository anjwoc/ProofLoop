from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proofloop_core.tokscale import TokScaleAdapter
from proofloop_core.usage import TokenLedger, UsageObservation


class TokScaleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root))
        (self.root / "run.json").write_text(json.dumps({"runId": "run-1"}), encoding="utf-8")
        (self.root / "invocations.jsonl").write_text(
            json.dumps(
                {
                    "invocationId": "01-codex-implementer_fast",
                    "role": "implementer_fast",
                    "runtime": "codex",
                    "requestedModel": "gpt-test",
                    "sessionId": "session-1",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        self.fake = self.root / "tokscale"
        self.fake.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "if '--version' in sys.argv:\n"
            " print('tokscale 4.5.3')\n"
            "else:\n"
            " print(json.dumps({'groupBy':'client,session,model','entries':["
            "{'sessionId':'session-1','client':'codex','model':'gpt-test','input':10,'output':5,'cacheRead':2,'cacheWrite':0,'reasoning':1,'cost':0.01},"
            "{'sessionId':'private-other-session','client':'codex','model':'gpt-private','input':999,'output':999}] }))\n",
            encoding="utf-8",
        )
        self.fake.chmod(0o755)

    def test_reconcile_filters_other_sessions_and_adds_cost(self) -> None:
        TokenLedger(self.root).record(
            UsageObservation(
                run_id="run-1",
                invocation_id="01-codex-implementer_fast",
                role="implementer_fast",
                runtime="codex",
                model="gpt-test",
                tokens={"input": 10, "output": 5, "cacheRead": 2, "cacheWrite": 0, "reasoning": 1},
                source="host_stream",
                measurement_kind="final",
                session_id="session-1",
            )
        )

        result = TokScaleAdapter(str(self.fake)).reconcile(self.root)

        self.assertEqual("PASS", result["status"])
        self.assertEqual("VERIFIED", result["matches"][0]["status"])
        raw = json.loads((self.root / "usage" / "tokscale-raw.json").read_text())
        self.assertEqual(["session-1"], [item["sessionId"] for item in raw["entries"]])
        summary = json.loads((self.root / "usage" / "usage-summary.json").read_text())
        self.assertEqual(0.01, summary["totals"]["costUsd"])

    def test_missing_cli_is_reported_without_erasing_usage(self) -> None:
        adapter = TokScaleAdapter(str(self.root / "missing"))
        result = adapter.reconcile(self.root)
        self.assertEqual("UNAVAILABLE", result["status"])


if __name__ == "__main__":
    unittest.main()
