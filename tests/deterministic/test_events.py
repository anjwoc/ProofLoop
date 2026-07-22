from __future__ import annotations

import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from proofloop_core.context.events import (
    V2_EVENT_TYPES,
    EventBus,
    EventEmitter,
    EventStoreCorruptError,
    ProofLoopEvent,
)


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

    def test_complete_event_missing_required_fields_blocks_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            malformed = json.loads(event_line(1))
            malformed.pop("data")
            (root / "events.jsonl").write_text(json.dumps(malformed) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(EventStoreCorruptError, "line 1"):
                EventEmitter("run-1", root, io.StringIO(), "quiet")

    def test_event_id_must_match_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            malformed = json.loads(event_line(2))
            malformed["eventId"] = "evt-000001"
            (root / "events.jsonl").write_text(json.dumps(malformed) + "\n", encoding="utf-8")

            with self.assertRaisesRegex(EventStoreCorruptError, "eventId"):
                EventEmitter("run-1", root, io.StringIO(), "quiet")


class EventBusTest(unittest.TestCase):
    def test_bus_fans_out_typed_event_to_multiple_subscribers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emitter = EventEmitter("run-1", root, io.StringIO(), "quiet")
            received_a: list[ProofLoopEvent] = []
            received_b: list[ProofLoopEvent] = []
            emitter.bus.subscribe(received_a.append)
            emitter.bus.subscribe(received_b.append)

            emitter.emit("strategy.selected", phase="CLASSIFY", message="Strategy selected.", data={"strategy": "DIRECT"})

            self.assertEqual(1, len(received_a))
            self.assertEqual(1, len(received_b))
            event = received_a[0]
            self.assertIsInstance(event, ProofLoopEvent)
            self.assertEqual("strategy.selected", event.event_type)
            self.assertEqual("Strategy selected.", event.summary)
            self.assertEqual(1, event.sequence)
            self.assertEqual({"strategy": "DIRECT"}, event.payload)

    def test_subscriber_exception_does_not_break_emit_or_other_subscribers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emitter = EventEmitter("run-1", root, io.StringIO(), "quiet")
            good: list[ProofLoopEvent] = []

            def boom(_event: ProofLoopEvent) -> None:
                raise RuntimeError("subscriber failure must not break the log")

            emitter.bus.subscribe(boom)
            emitter.bus.subscribe(good.append)

            event = emitter.emit("run.started", phase="INIT", message="Run started.")

            # the event log (source of truth) is intact regardless of subscriber failure
            stored = json.loads((root / "events.jsonl").read_text(encoding="utf-8").strip())
            self.assertEqual(event, stored)
            self.assertEqual(1, len(good))

    def test_unsubscribe_stops_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emitter = EventEmitter("run-1", root, io.StringIO(), "quiet")
            seen: list[ProofLoopEvent] = []
            unsubscribe = emitter.bus.subscribe(seen.append)
            emitter.emit("run.started", phase="INIT", message="one")
            unsubscribe()
            emitter.emit("run.completed", phase="TRUTH", message="two")
            self.assertEqual(["run.started"], [event.event_type for event in seen])

    def test_default_emitter_has_a_bus_with_no_subscribers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            emitter = EventEmitter("run-1", Path(tmp), io.StringIO(), "quiet")
            self.assertIsInstance(emitter.bus, EventBus)
            # emitting with no subscribers must not raise
            emitter.emit("run.started", phase="INIT", message="Run started.")


class ProofLoopEventTest(unittest.TestCase):
    def test_from_v1_dict_maps_fields(self) -> None:
        v1 = json.loads(event_line(5))
        v1["taskId"] = "TASK-1"
        v1["data"] = {"model": "gpt-5.6-terra", "host": "codex", "role": "implementer_fast", "artifact": "x.json"}
        event = ProofLoopEvent.from_v1_dict(v1)
        self.assertEqual("evt-000005", event.event_id)
        self.assertEqual("run.started", event.event_type)
        self.assertEqual("Run started.", event.summary)
        self.assertEqual("info", event.severity)
        self.assertEqual("TASK-1", event.task_id)
        self.assertEqual("gpt-5.6-terra", event.model)
        self.assertEqual("codex", event.host)
        self.assertEqual(("x.json",), event.artifact_refs)


class RedactionTest(unittest.TestCase):
    def test_secrets_are_redacted_before_persist_render_and_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stream = io.StringIO()
            emitter = EventEmitter("run-1", root, stream, "jsonl")
            captured: list[ProofLoopEvent] = []
            emitter.bus.subscribe(captured.append)
            secret = "sk-abcdefghijklmnopqrstuvwxyz0123"

            event = emitter.emit("role.output", phase="EXECUTE", message="ok", data={"line": f"key={secret}"})

            stored = (root / "events.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(secret, stored)
            self.assertIn("<REDACTED>", stored)
            self.assertNotIn(secret, stream.getvalue())
            self.assertNotIn(secret, json.dumps(event))
            self.assertNotIn(secret, json.dumps(captured[0].payload))


class EventTypeRegistryTest(unittest.TestCase):
    def test_v2_canonical_types_include_lifecycle_and_verdict(self) -> None:
        for required in ("run.started", "request.envelope_created", "verdict.issued", "grounding.started", "prompt_ir.created"):
            self.assertIn(required, V2_EVENT_TYPES)


if __name__ == "__main__":
    unittest.main()
