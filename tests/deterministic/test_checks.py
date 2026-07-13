from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

from proofloop_core.checks import run_checks
from proofloop_core.task_brief import load_task_brief


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

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
        event = {
            "type": event_type,
            "phase": phase,
            "message": message,
            "level": level,
            "taskId": task_id,
            "data": data or {},
            "recordedAt": time.monotonic(),
        }
        self.events.append(event)
        return event


class CheckRunnerTest(unittest.TestCase):
    def test_exit_code_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = root / "task.json"
            task_path.write_text(json.dumps({
                "id": "TASK-1",
                "objective": "prove failure",
                "allowedPaths": [],
                "protectedPaths": [],

                "changeBudget": {"maxChangedFiles": 8, "maxAddedLines": 500, "maxNewFiles": 4, "allowDependencyChanges": False},
                "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "bounded fixture change", "considered": ["reuse existing test harness"]},
                "requiredChecks": [{"command": ["python3", "-c", "import sys; print('no'); sys.exit(7)"]}]
            }), encoding="utf-8")
            emitter = RecordingEmitter()
            report = run_checks(load_task_brief(task_path), root, root / "evidence", emitter=emitter)
            self.assertEqual("FAIL", report["verdict"])
            self.assertEqual(7, report["checks"][0]["exitCode"])
            self.assertTrue(Path(report["checks"][0]["stdoutRef"]).exists())
            types = [event["type"] for event in emitter.events]
            self.assertEqual("check.started", types[0])
            self.assertIn("check.output", types)
            self.assertEqual("check.failed", types[-1])
            self.assertEqual(7, emitter.events[-1]["data"]["exitCode"])
            self.assertEqual("command exited with 7", emitter.events[-1]["data"]["failureReason"])
            self.assertIn("no", emitter.events[-1]["data"]["outputTail"])

    def test_slow_check_output_is_emitted_before_command_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task_path = root / "task.json"
            task_path.write_text(
                json.dumps(
                    {
                        "id": "TASK-1",
                        "objective": "stream output",
                        "allowedPaths": [],
                        "protectedPaths": [],
                        "changeBudget": {"maxChangedFiles": 1, "maxAddedLines": 1, "maxNewFiles": 0, "allowDependencyChanges": False},
                        "simplicity": {"selectedRung": "DIRECT_CHANGE", "rationale": "fixture", "considered": []},
                        "requiredChecks": [
                            {
                                "name": "slow",
                                "command": [
                                    "python3",
                                    "-u",
                                    "-c",
                                    "import time; print('early', flush=True); time.sleep(.6); print('late', flush=True)",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            emitter = RecordingEmitter()
            started = time.monotonic()

            report = run_checks(load_task_brief(task_path), root, root / "evidence", emitter=emitter)
            finished = time.monotonic()

            output_events = [event for event in emitter.events if event["type"] == "check.output"]
            self.assertEqual("PASS", report["verdict"])
            self.assertEqual(2, len(output_events))
            self.assertLess(output_events[0]["recordedAt"] - started, 0.4)
            self.assertGreater(finished - started, 0.5)


if __name__ == "__main__":
    unittest.main()
