from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from proofloop_core.run_state import start_run


ROOT = Path(__file__).resolve().parents[2]


class ClaudeHookTest(unittest.TestCase):
    def test_trace_hook_records_resolved_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            active = start_run(repo, "test")
            payload = {
                "cwd": str(repo),
                "tool_name": "Agent",
                "tool_use_id": "tool-1",
                "tool_input": {"subagent_type": "proofloop:proofloop-implementer-fast", "model": "haiku"},
                "tool_response": {"resolvedModel": "claude-haiku-4-5", "agentId": "agent-1", "status": "completed", "totalTokens": 123}
            }
            completed = subprocess.run(["python3", "scripts/claude_trace_hook.py"], cwd=ROOT, input=json.dumps(payload), text=True, capture_output=True, check=False)
            self.assertEqual(0, completed.returncode, completed.stderr)
            events = (Path(active["runDir"]) / "model-trace.jsonl").read_text(encoding="utf-8")
            self.assertIn("claude-haiku-4-5", events)
            summary = json.loads((Path(active["runDir"]) / "model-trace-summary.json").read_text(encoding="utf-8"))
            self.assertIn("implementer_fast", summary["observedModelsByRole"])

    def test_stop_hook_blocks_missing_truth_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            active = start_run(repo, "test")
            payload = {"cwd": str(repo), "stop_hook_active": False}
            blocked = subprocess.run(["python3", "scripts/claude_stop_hook.py"], cwd=ROOT, input=json.dumps(payload), text=True, capture_output=True, check=False)
            self.assertEqual(2, blocked.returncode)
            (Path(active["runDir"]) / "truth-report.json").write_text('{"verdict":"FAILED"}\n', encoding="utf-8")
            allowed = subprocess.run(["python3", "scripts/claude_stop_hook.py"], cwd=ROOT, input=json.dumps(payload), text=True, capture_output=True, check=False)
            self.assertEqual(0, allowed.returncode)


if __name__ == "__main__":
    unittest.main()
