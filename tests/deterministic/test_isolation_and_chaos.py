from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from proofloop_core.engine.chaos import ChaosController, ChaosInjectionError
from proofloop_core.runtimes.xdg_sandbox_runner import XdgSandboxRunner


def test_xdg_runner_keeps_agent_state_under_the_invocation(tmp_path: Path) -> None:
    invocation = tmp_path / "run" / "invocations" / "01-test"
    stdout = invocation / "stdout.log"
    result = XdgSandboxRunner().run(
        [
            sys.executable,
            "-c",
            "import json, os; print(json.dumps({key: os.environ[key] for key in ('HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME', 'XDG_STATE_HOME', 'CODEX_HOME')}))",
        ],
        cwd=tmp_path,
        stdout_path=stdout,
        stderr_path=invocation / "stderr.log",
        env={"UNCHANGED_PARENT_INPUT": "yes"},
        timeout_seconds=5,
    )

    isolated = json.loads(stdout.read_text(encoding="utf-8"))
    sandbox = invocation / "sandbox"
    assert result.exit_code == 0
    assert all(Path(value).is_relative_to(sandbox) for value in isolated.values())


def test_chaos_faults_are_named_and_deterministic() -> None:
    chaos = ChaosController(["token_limit"])

    with pytest.raises(ChaosInjectionError, match="token_limit"):
        chaos.execute_with_chaos("token_limit", lambda: "must not run")

    assert chaos.triggered == ["token_limit"]
    assert chaos.execute_with_chaos("other", lambda: "runs") == "runs"
