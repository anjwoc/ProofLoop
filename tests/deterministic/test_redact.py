from __future__ import annotations

import unittest
from proofloop_core.context.redact import redact_secrets


class RedactTest(unittest.TestCase):
    def test_redacts_strings(self) -> None:
        self.assertEqual(
            redact_secrets("Here is my key sk-1234567890abcdefghij12345"),
            "Here is my key <REDACTED>"
        )

    def test_redacts_dicts(self) -> None:
        self.assertEqual(
            redact_secrets({"token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz", "safe": "value"}),
            {"token": "<REDACTED>", "safe": "value"}
        )

    def test_redacts_nested(self) -> None:
        self.assertEqual(
            redact_secrets([{"a": "AIza1234567890abcdefghijklmnopqrstuvwxy"}]),
            [{"a": "<REDACTED>"}]
        )

if __name__ == "__main__":
    unittest.main()
