from __future__ import annotations

import unittest

from proofloop_core.output_parsers import parser_for
from proofloop_core.output_parsers.antigravity import AntigravityOutputParser
from proofloop_core.output_parsers.claude import ClaudeOutputParser
from proofloop_core.output_parsers.codex import CodexOutputParser


class HostOutputParserTest(unittest.TestCase):
    def test_codex_structured_model_is_observed(self) -> None:
        events = CodexOutputParser().feed(
            "stdout", '{"type":"thread.started","model":"gpt-5.6-terra"}\n'
        )
        self.assertEqual(1, len(events))
        self.assertEqual("role.model_observed", events[0].event_type)
        self.assertEqual("gpt-5.6-terra", events[0].data["observedModel"])
        self.assertEqual("HOST_OUTPUT", events[0].data["evidenceLevel"])

    def test_claude_init_model_is_observed(self) -> None:
        events = ClaudeOutputParser().feed(
            "stdout",
            '{"type":"system","subtype":"init","model":"claude-opus-4-1"}\n',
        )
        self.assertEqual("claude-opus-4-1", events[0].data["observedModel"])
        self.assertEqual("HOST_OUTPUT", events[0].data["evidenceLevel"])

    def test_antigravity_resolved_model_is_observed_only_from_structured_output(self) -> None:
        parser = AntigravityOutputParser()
        events = parser.feed(
            "stdout",
            '{"event":"model_resolved","resolvedModel":"Gemini 3.5 Flash"}\n',
        )
        self.assertEqual("Gemini 3.5 Flash", events[0].data["observedModel"])
        self.assertEqual([], parser.feed("stdout", "Gemini 3.5 Flash completed the task.\n"))

    def test_free_form_success_sentence_is_ignored(self) -> None:
        self.assertEqual([], ClaudeOutputParser().feed("stdout", "All tests passed.\n"))
        self.assertEqual([], CodexOutputParser().feed("stdout", "Using gpt-5.6-terra now.\n"))

    def test_structured_rate_limit_permission_and_host_errors_are_normalized(self) -> None:
        rate = CodexOutputParser().feed(
            "stderr", '{"type":"error","code":"rate_limit","message":"Too many requests"}\n'
        )[0]
        permission = ClaudeOutputParser().feed(
            "stderr", '{"type":"permission_denied","message":"Approval required"}\n'
        )[0]
        host_error = AntigravityOutputParser().feed(
            "stderr", '{"event":"error","message":"Host crashed"}\n'
        )[0]

        self.assertEqual("capability.degraded", rate.event_type)
        self.assertEqual("RATE_LIMIT", rate.data["reasonCode"])
        self.assertEqual("warning", rate.level)
        self.assertEqual("PERMISSION_REQUIRED", permission.data["reasonCode"])
        self.assertEqual("HOST_ERROR", host_error.data["reasonCode"])
        self.assertEqual("error", host_error.level)

    def test_parser_factory_rejects_unknown_host(self) -> None:
        self.assertIsInstance(parser_for("codex"), CodexOutputParser)
        self.assertIsInstance(parser_for("antigravity"), AntigravityOutputParser)
        self.assertIsInstance(parser_for("claude-code"), ClaudeOutputParser)
        with self.assertRaisesRegex(ValueError, "unsupported host parser"):
            parser_for("other")


if __name__ == "__main__":
    unittest.main()
