from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from proofloop_core.context.redact import redact_secrets
from proofloop_core.renderers import build_renderer


class EventStoreCorruptError(RuntimeError):
    pass


_LEVELS = {"debug", "info", "warning", "error"}
_EVENT_ID = re.compile(r"^evt-[0-9]{6,}$")

# Canonical V2 event vocabulary (architecture section 18.2). This is the target
# set for observability; not every type is emitted yet — later phases add
# grounding.*, prompt_ir.*, verdict.issued, etc. The registry gives future work
# a single authoritative list to emit against and guards against typos.
V2_EVENT_TYPES: frozenset[str] = frozenset({
    # lifecycle
    "run.created", "run.started", "run.completed", "run.cancelled", "run.failed",
    # request
    "request.received", "request.envelope_created",
    # intent
    "intent_gate.started", "intent_gate.completed",
    "intent_gate.owner_decision_required", "intent_gate.blocked",
    # grounding
    "grounding.started", "grounding.file_read", "grounding.command_detected", "grounding.completed",
    # compilation
    "prompt_refinement.started", "prompt_refinement.completed", "prompt_refinement.repaired",
    "contract.validation_started", "contract.validation_failed", "contract.validated",
    # strategy
    "workload.classified", "strategy.selected", "model.selected", "skill.selected",
    "blueprint.created", "blueprint.validated",
    # prompt
    "prompt_ir.created", "role_prompt.rendered", "role_prompt.dispatched", "prompt.recompiled",
    # execution
    "role.started", "role.progress", "role.completed", "role.failed",
    "tool.called", "tool.completed", "command.started", "command.completed",
    "file.read", "file.changed", "diff.created",
    # recovery
    "failure.fingerprinted", "recovery.started", "recovery.completed",
    "retry.scheduled", "retry.exhausted",
    # proof
    "check.started", "check.passed", "check.failed", "evidence.collected", "evidence.invalidated",
    "proof_obligation.created", "proof_obligation.satisfied", "proof_obligation.failed",
    "review.started", "review.completed", "verdict.issued",
})


@dataclass(frozen=True)
class ProofLoopEvent:
    """Typed, in-memory view of an emitted event (architecture section 18.1).

    This is a projection over the persisted v1 event dict; it never changes what
    is written to ``events.jsonl``. Subscribers on the EventBus receive these.
    """

    event_id: str
    run_id: str
    sequence: int
    timestamp: str
    event_type: str
    phase: str
    summary: str
    severity: str
    payload: dict[str, Any]
    task_id: str | None = None
    actor: str | None = None
    model: str | None = None
    host: str | None = None
    role: str | None = None
    artifact_refs: tuple[str, ...] = ()

    @classmethod
    def from_v1_dict(cls, event: dict[str, Any]) -> "ProofLoopEvent":
        data = dict(event.get("data") or {})
        refs = data.get("artifactRefs")
        if refs is None:
            single = data.get("artifact")
            refs = [single] if isinstance(single, str) else []
        return cls(
            event_id=event["eventId"],
            run_id=event["runId"],
            sequence=event["sequence"],
            timestamp=event["timestamp"],
            event_type=event["type"],
            phase=event["phase"],
            summary=event["message"],
            severity=event["level"],
            payload=data,
            task_id=event.get("taskId"),
            actor=data.get("actor"),
            model=data.get("model"),
            host=data.get("host"),
            role=data.get("role"),
            artifact_refs=tuple(str(item) for item in refs),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "2.0",
            "eventId": self.event_id,
            "runId": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "eventType": self.event_type,
            "phase": self.phase,
            "actor": self.actor,
            "model": self.model,
            "host": self.host,
            "role": self.role,
            "taskId": self.task_id,
            "summary": self.summary,
            "payload": self.payload,
            "artifactRefs": list(self.artifact_refs),
            "severity": self.severity,
        }


class EventBus:
    """In-process publish/subscribe fan-out over emitted events.

    Built before any UI (architecture section 18). A failing subscriber must
    never break the event log, so publish isolates each subscriber.
    """

    def __init__(self) -> None:
        self._subscribers: list[Callable[[ProofLoopEvent], None]] = []
        self._lock = threading.RLock()

    def subscribe(self, callback: Callable[[ProofLoopEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def publish(self, event: ProofLoopEvent) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber(event)
            except Exception:
                # The persisted event log is the source of truth; a subscriber
                # error is contained and never propagated to the write path.
                continue

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)


def validate_event(event: Any, *, expected_run_id: str | None = None) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("event must be an object")
    required_strings = ("eventId", "runId", "timestamp", "type", "phase", "message")
    if event.get("schemaVersion") != "1":
        raise ValueError("schemaVersion must be '1'")
    if any(not isinstance(event.get(key), str) or not event[key] for key in required_strings):
        raise ValueError("required string field is missing")
    if not _EVENT_ID.fullmatch(event["eventId"]):
        raise ValueError("invalid eventId")
    if expected_run_id is not None and event["runId"] != expected_run_id:
        raise ValueError("runId mismatch")
    sequence = event.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("sequence must be a positive integer")
    if event["eventId"] != f"evt-{sequence:06d}":
        raise ValueError("eventId does not match sequence")
    if event.get("level") not in _LEVELS:
        raise ValueError("invalid event level")
    if not isinstance(event.get("data"), dict):
        raise ValueError("data must be an object")
    if "taskId" in event and (not isinstance(event["taskId"], str) or not event["taskId"]):
        raise ValueError("taskId must be a non-empty string")
    try:
        timestamp = datetime.fromisoformat(event["timestamp"])
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return event


class DebugTraceProxy:
    """Proxy listener that records all lifecycle events and compiled prompts into a single debug trace file."""

    def __init__(self, run_dir: Path) -> None:
        self.trace_path = run_dir / "debug-trace.md"
        self._lock = threading.RLock()
        self._initialized = False

    def on_event(self, event: ProofLoopEvent) -> None:
        with self._lock:
            if not self._initialized:
                header = (
                    "# ProofLoop Debug Trace\n\n"
                    f"- **Run ID**: `{event.run_id}`\n"
                    f"- **Created At**: `{event.timestamp}`\n\n"
                    "---\n\n"
                )
                self.trace_path.write_text(header, encoding="utf-8")
                self._initialized = True

            lines: list[str] = []
            payload = event.payload or {}
            event_type = event.event_type

            if event_type == "run.started":
                req = payload.get("request") or event.summary
                lines.append(f"## [{event.phase}] Run Started\n- **Request**:\n```text\n{req}\n```\n")

            elif event_type == "strategy.selected":
                strat = payload.get("strategy") or event.summary
                lines.append(
                    f"## [{event.phase}] Strategy Selected\n"
                    f"- **Strategy**: `{strat}`\n"
                    f"- **Details**: `{json.dumps(payload, ensure_ascii=False)}`\n"
                )

            elif event_type == "role_prompt.rendered":
                role = event.role or payload.get("role") or "unknown"
                model = event.model or payload.get("model") or "unknown"
                reason = payload.get("reason") or "role dispatch"
                prompt_text = payload.get("promptText") or ""
                lines.append(
                    f"## [{event.phase}] Model selected & Prompt compiled\n"
                    f"- **Role**: `{role}`\n"
                    f"- **Model**: `{model}`\n"
                    f"- **Reason**: `{reason}`\n\n"
                    f"### Compiled Prompt IR\n```text\n{prompt_text}\n```\n"
                )

            elif event_type == "role.started":
                role = event.role or payload.get("role") or "unknown"
                lines.append(f"### ▶ Role Started: `{role}` (attempt {payload.get('attempt')})\n")

            elif event_type == "role.model_observed":
                lines.append(
                    f"### Model Observed: `{event.role or 'unknown'}`\n"
                    f"- Requested: `{payload.get('requestedModel')}`\n"
                    f"- Observed: `{payload.get('observedModel')}`\n"
                    f"- Evidence: `{payload.get('evidenceLevel')}`\n"
                )

            elif event_type in {"check.completed", "check.failed"}:
                verdict = "PASS" if event_type == "check.completed" else "FAIL"
                cmd = " ".join(str(p) for p in payload.get("command", []))
                lines.append(
                    f"### Verification Check: {verdict}\n"
                    f"- **Command**: `{cmd}`\n"
                    f"- **Exit Code**: `{payload.get('exitCode')}`\n"
                )
                if payload.get("outputTail"):
                    tail = "\n".join(payload["outputTail"])
                    lines.append(f"```text\n{tail}\n```\n")

            elif event_type == "diff_guard.completed":
                lines.append(
                    f"### Diff Guard: `{payload.get('verdict')}`\n"
                    f"- **Metrics**: `{json.dumps(payload.get('metrics', {}), ensure_ascii=False)}`\n"
                )

            elif event_type == "truth.completed":
                lines.append(
                    f"## [{event.phase}] Truth Verdict Issued\n"
                    f"- **Verdict**: `{payload.get('status') or payload.get('verdict')}`\n"
                    f"- **Summary**: `{event.summary}`\n"
                )

            if lines:
                with self.trace_path.open("a", encoding="utf-8") as handle:
                    handle.write("\n".join(lines) + "\n")
                    handle.flush()


class EventEmitter:
    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        stream: TextIO,
        output_format: str,
        verbosity: str = "info",
        color: str = "auto",
        bus: "EventBus | None" = None,
    ) -> None:
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.run_dir / "events.jsonl"
        self.renderer = build_renderer(output_format, stream, verbosity, color)
        self.bus = bus if bus is not None else EventBus()
        self.debug_trace = DebugTraceProxy(self.run_dir)
        self.bus.subscribe(self.debug_trace.on_event)
        self._lock = threading.RLock()
        self._render_enabled = True
        self._sequence = self._recover_sequence()

    def emit(
        self,
        event_type: str,
        *,
        phase: str,
        message: str,
        level: str = "info",
        task_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if level not in {"debug", "info", "warning", "error"}:
            raise ValueError(f"unsupported event level: {level}")
        with self._lock:
            self._sequence += 1
            event: dict[str, Any] = {
                "schemaVersion": "1",
                "eventId": f"evt-{self._sequence:06d}",
                "runId": self.run_id,
                "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "sequence": self._sequence,
                "type": event_type,
                "level": level,
                "phase": phase,
                "message": message,
                "data": dict(data or {}),
            }
            if task_id is not None:
                event["taskId"] = task_id
            # Redact secrets before the event touches disk, the render stream, the
            # return value, or the bus — so persistence/render/return/publish all
            # see one identical, scrubbed object.
            event["message"] = redact_secrets(event["message"])
            event["data"] = redact_secrets(event["data"])
            serialized = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(serialized + "\n")
                handle.flush()
            if self._render_enabled:
                try:
                    self.renderer.render(event)
                except BrokenPipeError:
                    self._render_enabled = False
            self.bus.publish(ProofLoopEvent.from_v1_dict(event))
            return event

    def _recover_sequence(self) -> int:
        if not self.path.exists():
            return 0
        text = self.path.read_text(encoding="utf-8")
        if not text:
            return 0
        if not text.endswith("\n"):
            last_newline = text.rfind("\n")
            tail = text[last_newline + 1 :]
            try:
                json.loads(tail)
            except json.JSONDecodeError:
                corrupt = self.run_dir / "events.corrupt-tail.log"
                if corrupt.exists() and corrupt.stat().st_size:
                    with corrupt.open("a", encoding="utf-8") as handle:
                        handle.write("\n" + tail)
                else:
                    corrupt.write_text(tail, encoding="utf-8")
                text = text[: last_newline + 1]
                self.path.write_text(text, encoding="utf-8")
            else:
                text += "\n"
                self.path.write_text(text, encoding="utf-8")

        last_sequence = 0
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EventStoreCorruptError(f"invalid event JSON at line {line_number}: {exc.msg}") from exc
            try:
                validate_event(event, expected_run_id=self.run_id)
            except ValueError as exc:
                raise EventStoreCorruptError(f"invalid event schema at line {line_number}: {exc}") from exc
            sequence = event["sequence"]
            if sequence <= last_sequence:
                raise EventStoreCorruptError(f"non-monotonic sequence at line {line_number}")
            last_sequence = sequence
        return last_sequence
