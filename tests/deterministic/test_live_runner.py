from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[2]


def _live_runner_module():
    spec = importlib.util.spec_from_file_location("proofloop_live_runner", ROOT / "scripts" / "run_host_live.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveRunnerContractTest(unittest.TestCase):
    def test_host_transcripts_are_outside_the_repository_fixture(self) -> None:
        module = _live_runner_module()
        holder, workspace = module.init_workspace("normal")
        try:
            transcript_dir = module.host_transcript_dir(workspace)
            self.assertEqual(workspace.parent, transcript_dir.parent)
            self.assertNotEqual(workspace, transcript_dir)
            self.assertFalse(str(transcript_dir).startswith(str(workspace) + "/"))
        finally:
            holder.cleanup()

    def test_live_runner_waits_for_a_detached_relay_from_any_host(self) -> None:
        module = _live_runner_module()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp) / "workspace"
            relay = workspace / ".proofloop" / "relay" / "one"
            relay.mkdir(parents=True)
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(.08)"])
            try:
                (relay / "pid").write_text(str(child.pid), encoding="utf-8")
                module.wait_for_background_relays(workspace, 2, poll_seconds=0.01)
                self.assertIsNotNone(child.poll())
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()

    def test_interrupted_run_is_retained_as_an_attempt_not_rewritten_as_truth(self) -> None:
        module = _live_runner_module()
        with tempfile.TemporaryDirectory() as tmp:
            module.ROOT = Path(tmp) / "project"
            workspace = Path(tmp) / "workspace"
            run = workspace / ".proofloop" / "runs" / "run-1"
            run.mkdir(parents=True)
            (workspace / "claude-code-stream.jsonl").write_text("partial host output\n", encoding="utf-8")
            report = module.save_acceptance_report(
                "claude-code",
                "interrupted-test",
                {"verdict": "FAILED", "reason": "TRUTH_REPORT_MISSING", "runDir": str(run), "workspace": str(workspace)},
            )
            assert report is not None
            self.assertTrue((report / "acceptance-attempt.json").is_file())
            self.assertFalse((report / "truth-report.json").exists())

    def test_fake_claude_without_run_artifacts_fails_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "claude"
            fake.write_text("#!/bin/sh\necho '{\"type\":\"result\"}'\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            completed = subprocess.run(
                ["python3", "scripts/run_claude_live.py", "--claude-bin", str(fake), "--max-budget-usd", "0.01"],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("NO_PROOFLOOP_RUN", completed.stdout)

    def test_fake_codex_without_run_artifacts_fails_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "codex"
            fake.write_text("#!/bin/sh\necho '{\"type\":\"turn.completed\"}'\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            completed = subprocess.run(
                ["python3", "scripts/run_host_live.py", "--host", "codex", "--binary", str(fake), "--no-save-report"],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("NO_PROOFLOOP_RUN", completed.stdout)

    def test_fake_antigravity_without_run_artifacts_fails_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "agy"
            fake.write_text("#!/bin/sh\necho done\nexit 0\n", encoding="utf-8")
            fake.chmod(0o755)
            completed = subprocess.run(
                ["python3", "scripts/run_host_live.py", "--host", "antigravity", "--binary", str(fake), "--no-save-report"],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("NO_PROOFLOOP_RUN", completed.stdout)


if __name__ == "__main__":
    unittest.main()
