from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from proofloop_core import mcp_server


class _Context:
    pass


class _FakeOrchestrator:
    def __init__(self, host: str, repository: Path, request: str, *, mode: str) -> None:
        self.host = host
        self.repository = repository
        self.request = request
        self.mode = mode
        self.run_dir: Path | None = None

    def run(self) -> dict[str, str]:
        self.run_dir = self.repository / ".proofloop" / "runs" / "run-test"
        self.run_dir.mkdir(parents=True)
        (self.run_dir / "events.jsonl").write_text(
            json.dumps({"sequence": 1, "type": "run.started"}) + "\n"
            + json.dumps({"sequence": 2, "type": "run.completed"}) + "\n",
            encoding="utf-8",
        )
        (self.run_dir / "run-outcome.json").write_text(
            json.dumps({"runId": "run-test", "verdict": "PROVEN", "summary": "proven"}),
            encoding="utf-8",
        )
        return {"runId": "run-test", "verdict": "PROVEN"}


def test_mcp_start_and_status_expose_core_owned_artifacts(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    monkeypatch.setattr(mcp_server, "ProofLoopOrchestrator", _FakeOrchestrator)
    mcp_server._sessions.clear()

    started = json.loads(
        mcp_server.proofloop_start_run(
            "Fix the bounded bug.",
            "fake-host",
            _Context(),
            repository=str(tmp_path),
        )
    )
    status = started
    for _ in range(20):
        status = json.loads(mcp_server.proofloop_run_status(started["sessionId"], _Context()))
        if status["status"] == "COMPLETED":
            break
        time.sleep(0.01)

    assert status["status"] == "COMPLETED"
    assert status["runId"] == "run-test"
    assert [event["type"] for event in status["events"]] == ["run.started", "run.completed"]
    assert status["outcome"]["verdict"] == "PROVEN"
