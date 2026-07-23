from __future__ import annotations

import json
import sys
from pathlib import Path

from proofloop_core.runtimes.host_runner import _agy_initial_output_timeout_seconds, invoke_role


def test_agy_has_no_hidden_initial_output_timeout(monkeypatch) -> None:
    monkeypatch.delenv("PROOFLOOP_AGY_INITIAL_OUTPUT_TIMEOUT_SECONDS", raising=False)
    assert _agy_initial_output_timeout_seconds(300) is None


def test_agy_initial_output_timeout_is_explicit_and_bounded(monkeypatch) -> None:
    monkeypatch.setenv("PROOFLOOP_AGY_INITIAL_OUTPUT_TIMEOUT_SECONDS", "90")
    assert _agy_initial_output_timeout_seconds(300) == 90
    assert _agy_initial_output_timeout_seconds(60) == 60


def test_agy_provider_response_timeout_is_not_misreported_as_initial_output_timeout(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROOFLOOP_RUNTIME_ENGINE", "process")
    script = "import sys; print('Error: timeout waiting for response', file=sys.stderr); raise SystemExit(1)"

    result = invoke_role(
        "agy",
        "implementer_fast",
        tmp_path,
        tmp_path / "run",
        binary=sys.executable,
        fixed_args=("-c", script),
        timeout_seconds=17,
    )

    assert result["verdict"] == "FAIL"
    assert result["reasonCode"] == "HOST_PROVIDER_RESPONSE_TIMEOUT"
    assert result["timedOut"] is False
    invocation = json.loads((Path(result["invocationDir"]) / "invocation.json").read_text(encoding="utf-8"))
    assert "--print-timeout" in invocation["command"]
    assert "17s" in invocation["command"]
    assert invocation["initialOutputTimeoutSeconds"] is None
