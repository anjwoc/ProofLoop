from __future__ import annotations

import io
import unittest

from proofloop_core.renderers import build_renderer


def event(
    event_type: str,
    *,
    phase: str = "EXECUTE",
    level: str = "info",
    message: str = "message",
    data: dict | None = None,
) -> dict:
    return {
        "schemaVersion": "1",
        "eventId": "evt-000001",
        "runId": "run-1",
        "timestamp": "2026-07-14T10:31:54.213+09:00",
        "sequence": 1,
        "type": event_type,
        "level": level,
        "phase": phase,
        "message": message,
        "data": data or {},
    }


class RendererTest(unittest.TestCase):
    def test_info_hides_live_role_internals_while_verbose_shows_them(self) -> None:
        items = (
            event(
                "role.progress",
                phase="PLAN",
                data={
                    "role": "planner_deep",
                    "processId": 12345,
                    "elapsedSeconds": 5.0,
                },
            ),
            event(
                "role.output",
                phase="PLAN",
                data={
                    "role": "planner_deep",
                    "stream": "stdout",
                    "text": "working on plan",
                },
            ),
        )
        info = io.StringIO()
        verbose = io.StringIO()
        for item in items:
            build_renderer("human", info, "info", "never").render(item)
            build_renderer("human", verbose, "verbose", "never").render(item)

        self.assertEqual("", info.getvalue())
        text = verbose.getvalue()
        self.assertIn("planner_deep running", text)
        self.assertIn("5.0s", text)
        self.assertIn("pid 12345", text)
        self.assertIn("planner_deep stdout", text)
        self.assertIn("working on plan", text)

    def test_human_renderer_separates_requested_and_unobserved_model(self) -> None:
        stream = io.StringIO()
        renderer = build_renderer("human", stream, "verbose", "never")

        renderer.render(
            event(
                "role.model_observed",
                level="warning",
                message="Model observation unavailable.",
                data={
                    "role": "implementer_fast",
                    "requestedModel": "Gemini Flash",
                    "observedModel": None,
                    "evidenceLevel": "CLI_REQUESTED_ONLY",
                },
            )
        )

        text = stream.getvalue()
        self.assertIn("[ProofLoop][EXECUTE]", text)
        self.assertIn("requested: Gemini Flash", text)
        self.assertIn("observed: unavailable", text)
        self.assertIn("routing proof: UNPROVEN", text)
        self.assertNotIn("\x1b[", text)

    def test_human_renderer_shows_session_activity_and_model_change(self) -> None:
        stream = io.StringIO()
        renderer = build_renderer("human", stream, "verbose", "never")
        renderer.render(
            event(
                "session.update",
                data={"role": "implementer_fast", "kind": "tool_call_started", "text": "write_file"},
            )
        )
        renderer.render(
            event(
                "model.changed",
                data={
                    "previousModel": "haiku",
                    "activeModel": "pro",
                    "evidenceLevel": "ACP_SESSION_CONFIG",
                    "reason": "recovery",
                },
            )
        )
        text = stream.getvalue()
        self.assertIn("tool ▶ write_file", text)
        self.assertIn("haiku → pro", text)
        self.assertIn("ACP_SESSION_CONFIG", text)

    def test_human_renderer_shows_live_and_completed_usage(self) -> None:
        stream = io.StringIO()
        renderer = build_renderer("human", stream, "verbose", "never")
        renderer.render(
            event(
                "usage.observed",
                data={
                    "role": "implementer_fast",
                    "requestedModel": "gpt-test",
                    "tokens": {"input": 100, "output": 25},
                },
            )
        )
        renderer.render(
            event(
                "role.completed",
                data={
                    "role": "implementer_fast",
                    "usage": {"rawTotal": 125, "model": "gpt-test"},
                },
            )
        )
        self.assertIn("125 tokens", stream.getvalue())
        self.assertIn("gpt-test", stream.getvalue())

    def test_human_renderer_formats_role_check_recovery_review_and_truth(self) -> None:
        stream = io.StringIO()
        renderer = build_renderer("human", stream, "verbose", "never")
        renderer.render(event("role.started", data={"role": "implementer_fast", "attempt": 2}))
        renderer.render(
            event(
                "check.failed",
                phase="VERIFY",
                level="error",
                data={"command": ["python3", "-m", "unittest"], "exitCode": 1, "failedTests": ["test_value"]},
            )
        )
        renderer.render(
            event(
                "recovery.scheduled",
                phase="REPAIR",
                level="warning",
                data={
                    "fromRole": "implementer_fast",
                    "toRole": "implementer_recovery",
                    "fromRequestedModel": "fast-model",
                    "toRequestedModel": "recovery-model",
                    "reason": "same fingerprint",
                },
            )
        )
        renderer.render(event("review.fix_required", phase="REVIEW", data={"finding": "keyboard navigation missing"}))
        renderer.render(event("truth.completed", phase="TRUTH", data={"status": "PROVEN"}))

        text = stream.getvalue()
        self.assertIn("implementer_fast · attempt 2", text)
        self.assertIn("FAIL · exit 1", text)
        self.assertIn("test_value", text)
        self.assertIn("implementer_fast → implementer_recovery", text)
        self.assertIn("fast-model → recovery-model", text)
        self.assertIn("keyboard navigation missing", text)
        self.assertIn("PROVEN", text)

    def test_human_renderer_keeps_the_core_check_id_with_its_plain_label(self) -> None:
        stream = io.StringIO()
        renderer = build_renderer("human", stream, "info", "never")
        renderer.render(
            event(
                "check.completed",
                phase="VERIFY",
                data={"name": "static-web-browser-load", "exitCode": 0},
            )
        )
        self.assertIn("static-web-browser-load · 브라우저 로드", stream.getvalue())

    def test_info_hides_check_output_while_debug_shows_it(self) -> None:
        item = event(
            "check.output",
            phase="VERIFY",
            level="debug",
            data={"stream": "stdout", "text": "one streamed line\n"},
        )
        info_stream = io.StringIO()
        build_renderer("human", info_stream, "info", "never").render(item)
        debug_stream = io.StringIO()
        build_renderer("human", debug_stream, "debug", "never").render(item)

        self.assertEqual("", info_stream.getvalue())
        self.assertIn("one streamed line", debug_stream.getvalue())

    def test_quiet_renderer_emits_nothing(self) -> None:
        stream = io.StringIO()
        build_renderer("quiet", stream, "info", "never").render(event("run.started"))
        self.assertEqual("", stream.getvalue())

    def test_info_shows_diff_and_failure_evidence_while_verbose_adds_metrics(self) -> None:
        info = io.StringIO()
        info_renderer = build_renderer("human", info, "info", "never")
        info_renderer.render(
            event(
                "diff_guard.failed",
                phase="VERIFY",
                level="error",
                data={
                    "verdict": "FAIL",
                    "metrics": {"changedFiles": 3, "addedLines": 42, "newFiles": 1},
                    "violations": [{"code": "SCOPE_VIOLATION", "path": "extra.py"}],
                    "artifact": "/tmp/diff-guard.json",
                },
            )
        )
        info_renderer.render(
            event(
                "check.failed",
                phase="VERIFY",
                level="error",
                data={
                    "exitCode": 7,
                    "failureReason": "command exited with 7",
                    "outputTail": ["FAIL test_payment", "expected 1, got 2"],
                    "stderrRef": "/tmp/check.stderr.log",
                },
            )
        )
        self.assertIn("DIFF GUARD FAIL", info.getvalue())
        self.assertIn("SCOPE_VIOLATION", info.getvalue())
        self.assertIn("command exited with 7", info.getvalue())
        self.assertIn("expected 1, got 2", info.getvalue())

        verbose = io.StringIO()
        verbose_renderer = build_renderer("human", verbose, "verbose", "never")
        verbose_renderer.render(
            event(
                "diff_guard.completed",
                phase="VERIFY",
                data={"verdict": "PASS", "metrics": {"changedFiles": 3, "addedLines": 42, "newFiles": 1}},
            )
        )
        verbose_renderer.render(
            event(
                "review.overbuilt",
                phase="REVIEW",
                level="warning",
                data={"deletionCandidates": ["unused abstraction"]},
            )
        )
        self.assertIn("3 files", verbose.getvalue())
        self.assertIn("+42 LOC", verbose.getvalue())
        self.assertIn("unused abstraction", verbose.getvalue())

    def test_debug_shows_invocation_and_artifact_references(self) -> None:
        stream = io.StringIO()
        renderer = build_renderer("human", stream, "debug", "never")
        renderer.render(
            event(
                "role.completed",
                data={
                    "role": "implementer_fast",
                    "exitCode": 0,
                    "invocationId": "02-codex-implementer_fast",
                    "invocationDir": "/tmp/invocations/02-codex-implementer_fast",
                },
            )
        )
        self.assertIn("02-codex-implementer_fast", stream.getvalue())
        self.assertIn("/tmp/invocations/02-codex-implementer_fast", stream.getvalue())

    def test_unknown_format_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "output format"):
            build_renderer("xml", io.StringIO(), "info", "never")


if __name__ == "__main__":
    unittest.main()
