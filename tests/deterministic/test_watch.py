from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from proofloop_core.watch import resolve_run_dir, watch_events


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
