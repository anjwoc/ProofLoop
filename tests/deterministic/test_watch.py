from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofloop_core.context.events import EventBus
from proofloop_core.ui.cli import main
from proofloop_core.ui.watch import WatchPanels, render_watch_panels, resolve_run_dir, watch_events


def make_event(
    sequence: int,
    event_type: str,
    *,
    level: str = "info",
    task_id: str | None = None,
) -> dict:
    value = {
        "schemaVersion": "1",
        "eventId": f"evt-{sequence:06d}",
        "runId": "run-1",
        "timestamp": "2026-07-14T10:31:54.213+09:00",
        "sequence": sequence,
        "type": event_type,
        "level": level,
        "phase": "VERIFY",
        "message": event_type,
        "data": {},
    }
    if task_id is not None:
        value["taskId"] = task_id
    return value


class WatchTest(unittest.TestCase):
    def test_watch_cli_panels_use_replayed_event_bus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            source = [
                make_event(1, "run.started"),
                {**make_event(2, "proof.updated"), "data": {"closureRatio": 1.0, "open": []}},
                {**make_event(3, "run.completed"), "data": {"verdict": "PROVEN"}},
            ]
            (run_dir / "events.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in source), encoding="utf-8"
            )
            stream = io.StringIO()

            with patch("sys.stdout", stream):
                result = main([
                    "watch", "--run-dir", str(run_dir), "--no-follow", "--panels", "--color", "never"
                ])

            self.assertEqual(0, result)
            self.assertIn("[ProofLoop Watch]", stream.getvalue())
            self.assertIn("status: PROVEN", stream.getvalue())
            self.assertIn("proof: 100% closed · open: none", stream.getvalue())

    def test_watch_replay_reconstructs_panels_via_event_bus(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            source = [
                make_event(1, "run.started"),
                {
                    **make_event(2, "strategy.selected"),
                    "data": {"tier": "T2", "strategy": "PLANNED_IMPLEMENTATION"},
                },
                {
                    **make_event(3, "role.started", task_id="TASK-001"),
                    "data": {"role": "implementer_fast", "requestedModel": "gpt-5.6-terra", "attempt": 1},
                },
                {
                    **make_event(4, "proof.updated"),
                    "data": {"closureRatio": 0.5, "open": ["deterministic-checks", "scope-integrity"]},
                },
                {
                    **make_event(5, "budget.updated", task_id="TASK-001"),
                    "data": {"consumedTokens": 120, "remainingTokens": 880, "maxTokens": 1000},
                },
                {
                    **make_event(6, "role.completed", task_id="TASK-001"),
                    "data": {"role": "implementer_fast", "attempt": 1},
                },
                {
                    **make_event(7, "usage.finalized"),
                    "data": {
                        "summary": {
                            "totals": {"rawTotal": 120},
                            "coverage": {"tokenCoverageRatio": 1.0},
                        }
                    },
                },
                {
                    **make_event(8, "run.completed"),
                    "data": {"verdict": "PROVEN"},
                },
            ]
            (run_dir / "events.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in source), encoding="utf-8"
            )

            first_bus = EventBus()
            first = WatchPanels()
            first_bus.subscribe(first.consume)
            watch_events(
                run_dir,
                stream=io.StringIO(),
                output_format="jsonl",
                follow=False,
                event_bus=first_bus,
            )

            second_bus = EventBus()
            second = WatchPanels()
            second_bus.subscribe(second.consume)
            watch_events(
                run_dir,
                stream=io.StringIO(),
                output_format="jsonl",
                follow=False,
                event_bus=second_bus,
            )

            self.assertEqual(first.snapshot(), second.snapshot())
            self.assertEqual("PROVEN", first.snapshot()["status"])
            self.assertEqual("T2", first.snapshot()["tier"])
            self.assertEqual(0.5, first.snapshot()["proof"]["closureRatio"])
            self.assertEqual(["deterministic-checks", "scope-integrity"], first.snapshot()["proof"]["open"])
            self.assertEqual(120, first.snapshot()["budget"]["consumedTokens"])
            self.assertEqual(1000, first.snapshot()["budget"]["maxTokens"])
            self.assertEqual(
                {"attempt": 1, "model": "gpt-5.6-terra", "status": "COMPLETED", "taskId": "TASK-001"},
                first.snapshot()["roles"]["implementer_fast"],
            )
            self.assertEqual(
                "[ProofLoop Watch]\n"
                "status: PROVEN\n"
                "tier: T2 · strategy: PLANNED_IMPLEMENTATION\n"
                "roles:\n"
                "  implementer_fast: COMPLETED · gpt-5.6-terra · TASK-001 · attempt 1\n"
                "proof: 50% closed · open: deterministic-checks, scope-integrity\n"
                "budget: 120 tokens · remaining 880 / max 1000 · coverage 1.0",
                render_watch_panels(first),
            )

    def test_panel_projection_receives_all_events_when_timeline_is_filtered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            source = [
                make_event(1, "run.started"),
                make_event(2, "check.failed", level="warning", task_id="TASK-002"),
                {**make_event(3, "run.completed"), "data": {"verdict": "PROVEN"}},
            ]
            (run_dir / "events.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in source), encoding="utf-8"
            )
            bus = EventBus()
            panels = WatchPanels()
            bus.subscribe(panels.consume)

            rendered = watch_events(
                run_dir,
                stream=io.StringIO(),
                output_format="jsonl",
                task_id="TASK-002",
                follow=False,
                event_bus=bus,
            )

            self.assertEqual(1, rendered)
            self.assertEqual("PROVEN", panels.snapshot()["status"])

    def test_watch_replays_filtered_complete_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            source = [
                make_event(1, "check.completed", task_id="TASK-001"),
                make_event(2, "check.failed", level="warning", task_id="TASK-002"),
                make_event(3, "run.failed", level="error"),
            ]
            (run_dir / "events.jsonl").write_text(
                "".join(json.dumps(event) + "\n" for event in source), encoding="utf-8"
            )
            stream = io.StringIO()

            count = watch_events(
                run_dir,
                stream=stream,
                output_format="jsonl",
                task_id="TASK-002",
                minimum_level="warning",
                follow=False,
            )

            events = [json.loads(line) for line in stream.getvalue().splitlines()]
            self.assertEqual(1, count)
            self.assertEqual([source[1]], events)

    def test_watch_ignores_incomplete_final_line_without_following(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            complete = make_event(1, "run.started")
            (run_dir / "events.jsonl").write_text(
                json.dumps(complete) + "\n" + '{"schemaVersion":"1"', encoding="utf-8"
            )
            stream = io.StringIO()

            count = watch_events(run_dir, stream=stream, output_format="jsonl", follow=False)

            self.assertEqual(1, count)
            self.assertEqual(complete, json.loads(stream.getvalue()))

    def test_resolve_latest_run_uses_lexically_newest_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            runs = repo / ".proofloop" / "runs"
            (runs / "20260714T100000-a").mkdir(parents=True)
            newest = runs / "20260714T100001-b"
            newest.mkdir()

            self.assertEqual(newest.resolve(), resolve_run_dir(repo=repo, run="latest"))
            self.assertEqual(
                (runs / "20260714T100000-a").resolve(),
                resolve_run_dir(repo=repo, run="20260714T100000-a"),
            )

    def test_watch_rejects_malformed_complete_line_with_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            (run_dir / "events.jsonl").write_text("not-json\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "line 1"):
                watch_events(run_dir, stream=io.StringIO(), output_format="jsonl", follow=False)

    def test_watch_rejects_valid_json_missing_required_event_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            malformed = make_event(1, "run.started")
            malformed.pop("message")
            (run_dir / "events.jsonl").write_text(json.dumps(malformed) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "line 1"):
                watch_events(run_dir, stream=io.StringIO(), output_format="jsonl", follow=False)

    def test_watch_rejects_event_id_sequence_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            malformed = make_event(2, "run.started")
            malformed["eventId"] = "evt-000001"
            (run_dir / "events.jsonl").write_text(json.dumps(malformed) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "eventId"):
                watch_events(run_dir, stream=io.StringIO(), output_format="jsonl", follow=False)


if __name__ == "__main__":
    unittest.main()
