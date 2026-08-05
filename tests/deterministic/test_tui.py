from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofloop_core.ui.cli import main
from proofloop_core.context.events import ProofLoopEvent
from proofloop_core.ui.tui import ProofLoopTUI


def make_event(
    sequence: int,
    event_type: str,
    *,
    level: str = "info",
    task_id: str | None = None,
    data: dict | None = None,
) -> dict:
    return {
        "schemaVersion": "1",
        "eventId": f"evt-{sequence:06d}",
        "runId": "pl-20260721-a82f",
        "timestamp": "2026-07-21T14:31:54.213+09:00",
        "sequence": sequence,
        "type": event_type,
        "level": level,
        "phase": "EXECUTE",
        "message": event_type,
        "data": data or {},
    }


class TuiTest(unittest.TestCase):
    def test_tui_state_consume_and_render_summary(self) -> None:
        tui = ProofLoopTUI()
        events = [
            make_event(1, "run.started", data={"request": "결제 재시도 시 중복 처리를 방지해줘", "host": "Codex"}),
            make_event(2, "intent_gate.completed", data={"intentKind": "MUTATE", "authorityLevel": "REPOSITORY_MUTATION"}),
            make_event(3, "strategy.selected", data={"tier": "T2", "strategy": "explore → plan → implement → verify"}),
            make_event(4, "role.started", data={"role": "implementer_deep", "requestedModel": "GPT-5.6 Sol", "attempt": 1, "taskId": "idempotency state boundary implementation"}),
            make_event(5, "proof.updated", data={"closureRatio": 0.4, "satisfied": ["request fidelity", "authority preserved", "regression reproduced"], "open": ["focused tests", "public contract unchanged"]}),
            make_event(6, "budget.updated", data={"consumedTokens": 48210, "remainingTokens": 71790, "maxTokens": 120000}),
        ]
        for ev in events:
            tui.consume(ProofLoopEvent.from_v1_dict(ev))

        screen = tui.render_tui_screen()
        self.assertIn("pl-20260721-a82f", screen)
        self.assertIn("결제 재시도 시 중복 처리를 방지해줘", screen)
        self.assertIn("MUTATE · REPOSITORY_MUTATION", screen)
        self.assertIn("T2", screen)
        self.assertIn("Codex", screen)
        self.assertIn("explore → plan → implement → verify", screen)
        self.assertIn("implementer_deep · GPT-5.6 Sol", screen)
        self.assertIn("✓ request fidelity", screen)
        self.assertIn("Tokens 48,210 / 120,000", screen)

    def test_tui_render_tabs(self) -> None:
        tui = ProofLoopTUI()
        events = [
            make_event(1, "role.started", data={"role": "implementer_fast", "requestedModel": "haiku", "attempt": 1}),
            make_event(2, "role_prompt.rendered", data={"irVersion": "v1", "renderer": "default", "role": "implementer_fast", "promptHash": "sha256:1234", "promptText": "System prompt line 1\nLine 2"}),
            make_event(3, "check.completed", data={"command": ["pytest", "tests/test_retry.py"]}),
        ]
        for ev in events:
            tui.consume(ProofLoopEvent.from_v1_dict(ev))

        prompts_tab = tui.render_tab("prompts")
        self.assertIn("Prompt IR", prompts_tab)
        self.assertIn("sha256:1234", prompts_tab)
        self.assertIn("System prompt line 1", prompts_tab)

        commands_tab = tui.render_tab("commands")
        self.assertIn("pytest tests/test_retry.py", commands_tab)

    def test_cli_tui_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "pl-100"
            run_dir.mkdir(parents=True)
            events = [
                make_event(1, "run.started", data={"request": "test request"}),
                make_event(2, "run.completed", data={"verdict": "PROVEN"}),
            ]
            (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

            stream = io.StringIO()
            with patch("sys.stdout", stream):
                res = main(["tui", "--run-dir", str(run_dir), "--no-follow"])
            self.assertEqual(0, res)
            self.assertIn("ProofLoop Run", stream.getvalue())
            self.assertIn("PROVEN", stream.getvalue())

    def test_cli_watch_tui_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "pl-101"
            run_dir.mkdir(parents=True)
            events = [
                make_event(1, "run.started", data={"request": "test watch tui"}),
            ]
            (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

            stream = io.StringIO()
            with patch("sys.stdout", stream):
                res = main(["watch", "--run-dir", str(run_dir), "--format", "tui", "--no-follow"])
            self.assertEqual(0, res)
            self.assertIn("test watch tui", stream.getvalue())

    def test_cli_relay_tui_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relay_dir = root / ".proofloop" / "relay" / "20260721T140000Z-123"
            relay_dir.mkdir(parents=True)
            run_dir = root / ".proofloop" / "runs" / "pl-latest"
            run_dir.mkdir(parents=True)

            (relay_dir / "output.log").write_text("[ProofLoop][SYSTEM] starting\n", encoding="utf-8")
            (relay_dir / "next-line").write_text("1\n", encoding="utf-8")

            events = [
                make_event(1, "run.started", data={"request": "relayed request"}),
            ]
            (run_dir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")

            stream = io.StringIO()
            with patch("sys.stdout", stream):
                res = main(["relay", "--relay-dir", str(relay_dir), "--wait-seconds", "0", "--tui"])
            self.assertEqual(0, res)
            self.assertIn("relayed request", stream.getvalue())
            self.assertIn("PROOFLOOP_RELAY_FINISHED", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
