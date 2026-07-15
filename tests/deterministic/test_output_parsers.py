from __future__ import annotations

import unittest

from proofloop_core.output_parsers import parser_for
from proofloop_core.output_parsers.antigravity import AntigravityOutputParser
from proofloop_core.output_parsers.claude import ClaudeOutputParser
from proofloop_core.output_parsers.codex import CodexOutputParser
from proofloop_core.output_parsers.gemini import GeminiOutputParser


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

    def test_codex_claude_and_gemini_stream_semantic_session_updates(self) -> None:
        codex = CodexOutputParser().feed(
            "stdout",
            '{"type":"item.completed","item":{"type":"agent_message","text":"implemented"}}\n',
        )
        claude = ClaudeOutputParser().feed(
            "stdout",
            '{"type":"assistant","message":{"content":[{"type":"tool_use","id":"t1","name":"Read"}]}}\n',
        )
        gemini = GeminiOutputParser().feed(
            "stdout",
            '{"type":"tool_result","tool_name":"write_file","status":"success"}\n',
        )
        self.assertEqual("agent_message_chunk", codex[0].data["kind"])
        self.assertEqual("tool_call_started", claude[0].data["kind"])
        self.assertEqual("tool_call_updated", gemini[0].data["kind"])
        self.assertIsInstance(parser_for("gemini"), GeminiOutputParser)

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

    def test_unrelated_or_nested_model_json_is_not_trusted(self) -> None:
        payloads = (
            '{"type":"assistant.message","model":"spoofed-top-level"}\n',
            '{"type":"result","result":{"model":"spoofed-nested"}}\n',
            '{"event":"tool_result","metadata":{"resolvedModel":"spoofed-metadata"}}\n',
        )
        for parser in (CodexOutputParser(), ClaudeOutputParser(), AntigravityOutputParser()):
            for payload in payloads:
                events = parser.feed("stdout", payload)
                self.assertFalse(any(item.event_type == "role.model_observed" for item in events))

    def test_provider_final_usage_is_normalized(self) -> None:
        cases = (
            (
                CodexOutputParser(),
                '{"type":"turn.completed","thread_id":"codex-s","usage":{"input_tokens":100,"output_tokens":20,"cached_input_tokens":30,"reasoning_output_tokens":4}}\n',
            ),
            (
                ClaudeOutputParser(),
                '{"type":"result","session_id":"claude-s","usage":{"input_tokens":101,"output_tokens":21,"cache_read_input_tokens":31}}\n',
            ),
            (
                GeminiOutputParser(),
                '{"type":"result","sessionId":"gemini-s","usageMetadata":{"promptTokenCount":102,"candidatesTokenCount":22,"cachedContentTokenCount":32,"thoughtsTokenCount":5}}\n',
            ),
            (
                AntigravityOutputParser(),
                '{"event":"result","sessionId":"ag-s","usage":{"input":103,"output":23,"cacheRead":33,"reasoning":6}}\n',
            ),
        )
        expected_inputs = (70, 101, 70, 103)
        for (parser, payload), expected_input in zip(cases, expected_inputs):
            event = next(item for item in parser.feed("stdout", payload) if item.event_type == "usage.observed")
            self.assertEqual(expected_input, event.data["tokens"]["input"])
            self.assertEqual("final", event.data["measurementKind"])
            self.assertTrue(event.data["sessionId"])

    def test_host_session_ids_are_normalized(self) -> None:
        events = (
            CodexOutputParser().feed("stdout", '{"type":"thread.started","thread_id":"c1"}\n'),
            ClaudeOutputParser().feed("stdout", '{"type":"system","subtype":"init","session_id":"c2"}\n'),
            GeminiOutputParser().feed("stdout", '{"type":"init","sessionId":"c3"}\n'),
            AntigravityOutputParser().feed("stdout", '{"event":"session_started","sessionId":"c4"}\n'),
        )
        self.assertEqual(["c1", "c2", "c3", "c4"], [items[0].data["sessionId"] for items in events])


if __name__ == "__main__":
    unittest.main()
