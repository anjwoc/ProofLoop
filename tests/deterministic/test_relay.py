from __future__ import annotations

from pathlib import Path

from proofloop_core.ui.relay import poll_relay


def test_relay_collapses_backlogged_progress_heartbeats(tmp_path: Path) -> None:
    (tmp_path / "output.log").write_text(
        "[ProofLoop][EXECUTE] ▶ implementer_fast · attempt 1\n"
        "[ProofLoop][EXECUTE] … implementer_fast running · 5.0s · pid 1\n"
        "[ProofLoop][EXECUTE] … implementer_fast running · 10.0s · pid 1\n"
        "[ProofLoop][EXECUTE] … implementer_fast running · 15.0s · pid 1\n"
        "[ProofLoop][EXECUTE] implementer_fast stderr: Error: timeout waiting for response\n",
        encoding="utf-8",
    )

    poll = poll_relay(tmp_path)

    assert poll.lines == (
        "[ProofLoop][EXECUTE] ▶ implementer_fast · attempt 1",
        "[ProofLoop][EXECUTE] … implementer_fast running · 15.0s · pid 1",
        "[ProofLoop][EXECUTE] implementer_fast stderr: Error: timeout waiting for response",
    )
    assert poll_relay(tmp_path).lines == ()
