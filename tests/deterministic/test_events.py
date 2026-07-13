from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from proofloop_core.events import EventEmitter, EventStoreCorruptError


class FlushTrackingStream(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1
        super().flush()


def event_line(sequence: int) -> str:
    return json.dumps(
        {
            "schemaVersion": "1",
            "eventId": f"evt-{sequence:06d}",
            "runId": "run-1",
            "timestamp": "2026-07-14T10:31:54.213+09:00",
            "sequence": sequence,
            "type": "run.started",
            "level": "info",
            "phase": "INIT",
            "message": "Run started.",
            "data": {},
        },
        separators=(",", ":"),
    )


class EventEmitterTest(unittest.TestCase):
    def test_event_is_persisted_and_rendered_from_same_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stream = FlushTrackingStream()
            emitter = EventEmitter("run-1", root, stream, "jsonl")

            event = emitter.emit("run.started", phase="INIT", message="Run started.")

            stored = json.loads((root / "events.jsonl").read_text(encoding="utf-8").strip())
            rendered = json.loads(stream.getvalue().strip())
            self.assertEqual(event, stored)
            self.assertEqual(stored, rendered)
            self.assertEqual(1, event["sequence"])
            self.assertEqual("evt-000001", event["eventId"])
            self.assertEqual("1", event["schemaVersion"])
            self.assertGreaterEqual(stream.flush_count, 1)

    def test_concurrent_emits_have_monotonic_unique_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emitter = EventEmitter("run-1", root, io.StringIO(), "quiet")
            threads = [
                threading.Thread(
                    target=emitter.emit,
                    args=("check.output",),
                    kwargs={"phase": "VERIFY", "message": f"line {index}"},
                )
                for index in range(32)
            ]

            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            events = [
                json.loads(line)
                for line in (root / "events.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(list(range(1, 33)), [event["sequence"] for event in events])
            self.assertEqual(32, len({event["eventId"] for event in events}))

    def test_restart_continues_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = EventEmitter("run-1", root, io.StringIO(), "quiet")
            first.emit("run.started", phase="INIT", message="Run started.")
            first.emit("strategy.selected", phase="CLASSIFY", message="Strategy selected.")

            second = EventEmitter("run-1", root, io.StringIO(), "quiet")
            event = second.emit("context.started", phase="CONTEXT", message="Context started.")

            self.assertEqual(3, event["sequence"])
            self.assertEqual("evt-000003", event["eventId"])

    def test_incomplete_final_fragment_is_quarantined_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "events.jsonl"
            path.write_text(event_line(1) + "\n" + '{"schemaVersion":"1"', encoding="utf-8")

            emitter = EventEmitter("run-1", root, io.StringIO(), "quiet")
            event = emitter.emit("run.completed", phase="TRUTH", message="Run completed.")

            self.assertEqual(2, event["sequence"])
            self.assertEqual('{"schemaVersion":"1"', (root / "events.corrupt-tail.log").read_text(encoding="utf-8"))
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(lines))
            self.assertEqual([1, 2], [json.loads(line)["sequence"] for line in lines])

    def test_complete_malformed_line_blocks_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "events.jsonl").write_text(event_line(1) + "\nnot-json\n", encoding="utf-8")

            with self.assertRaisesRegex(EventStoreCorruptError, "line 2"):
                EventEmitter("run-1", root, io.StringIO(), "quiet")


if __name__ == "__main__":
    unittest.main()
