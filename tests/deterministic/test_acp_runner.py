from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from proofloop_core.acp_runner import invoke_acp_role
from proofloop_core.runtime import ResolvedRuntime


@unittest.skipUnless(importlib.util.find_spec("acp"), "optional ACP SDK is not installed")
class ACPRunnerTest(unittest.TestCase):
    def test_official_sdk_session_streams_updates(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root))
        fixture = Path(__file__).resolve().parents[1] / "fixtures" / "fake_acp_agent.py"
        resolved = ResolvedRuntime(
            controller_host="codex",
            role="explorer_fast",
            runtime_id="codex",
            model="fixture-model",
            reasoning="low",
            access_mode="read-only",
            transport="acp",
            executable=sys.executable,
            fixed_args=(str(fixture),),
            fallback=False,
            reason="test fixture",
        )
        events: list[tuple[str, str, dict[str, object]]] = []

        result = invoke_acp_role(
            resolved,
            root,
            root / "invocation",
            "inspect the fixture",
            10,
            lambda event_type, message, data: events.append((event_type, message, data)),
        )

        self.assertEqual("PASS", result["verdict"], result)
        self.assertEqual("ACP_SESSION_CONFIG", result["modelEvidence"])
        self.assertIn("session.started", [event[0] for event in events])
        self.assertIn("model.resolved", [event[0] for event in events])
        update = next(event for event in events if event[0] == "session.update")
        self.assertEqual("agent_message_chunk", update[2]["kind"])
        self.assertIn("fixture ACP output", update[1])


if __name__ == "__main__":
    unittest.main()
