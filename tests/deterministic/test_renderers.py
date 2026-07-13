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
    def test_human_renderer_separates_requested_and_unobserved_model(self) -> None:
        stream = io.StringIO()
        renderer = build_renderer("human", stream, "info", "never")

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
                data={"fromRole": "implementer_fast", "toRole": "implementer_recovery", "reason": "same fingerprint"},
            )
        )
        renderer.render(event("review.fix_required", phase="REVIEW", data={"finding": "keyboard navigation missing"}))
        renderer.render(event("truth.completed", phase="TRUTH", data={"status": "PROVEN"}))

        text = stream.getvalue()
        self.assertIn("implementer_fast · attempt 2", text)
        self.assertIn("FAIL · exit 1", text)
        self.assertIn("test_value", text)
        self.assertIn("implementer_fast → implementer_recovery", text)
        self.assertIn("keyboard navigation missing", text)
        self.assertIn("PROVEN", text)

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

    def test_unknown_format_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "output format"):
            build_renderer("xml", io.StringIO(), "info", "never")


if __name__ == "__main__":
    unittest.main()
