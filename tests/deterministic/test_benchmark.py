from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from proofloop_core.benchmark import compare_trials, load_benchmark_suite, run_benchmark


def trial(arm: str, repetition: int, tokens: int, *, proven: bool = True) -> dict:
    mode = arm.split("-", 1)[1]
    return {
        "mode": mode,
        "arm": arm,
        "taskId": "task-1",
        "repetition": repetition,
        "verdict": "PROVEN" if proven else "FAILED",
        "usageAvailable": True,
        "costAvailable": True,
        "durationSeconds": 10,
        "usage": {"totals": {"rawTotal": tokens, "costUsd": tokens / 1000}},
    }


class BenchmarkTest(unittest.TestCase):
    def test_comparison_reports_quality_adjusted_token_gain(self) -> None:
        trials = []
        for repetition in range(1, 6):
            trials.append(trial("baseline-routing", repetition, 1000))
            trials.append(trial("proofloop-routing", repetition, 500))

        result = compare_trials(trials)["comparisons"][0]

        self.assertEqual("IMPROVED", result["status"])
        self.assertEqual(50.0, result["tokenEfficiencyGainPct"])
        self.assertEqual([50.0, 50.0], result["pairedTokenGain95CI"])
        self.assertEqual(1.0, result["proofloop"]["successRate"])

    def test_missing_usage_never_becomes_zero_token_efficiency(self) -> None:
        baseline = trial("baseline-system", 1, 1000)
        candidate = trial("proofloop-system", 1, 0)
        candidate["usageAvailable"] = False

        result = compare_trials([baseline, candidate])["comparisons"][0]

        self.assertIsNone(result["tokenEfficiencyGainPct"])
        self.assertEqual("INSUFFICIENT_DATA", result["status"])

    def test_suite_requires_argv_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "suite.json"
            path.write_text(json.dumps({"tasks": [{"id": "t", "request": "r", "checks": ["pytest"]}]}))
            with self.assertRaisesRegex(ValueError, "command arguments"):
                load_benchmark_suite(path)

    def test_runner_uses_isolated_worktrees_and_persists_trials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "qa@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "QA"], cwd=repo, check=True)
            (repo / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True)
            suite = repo / "suite.json"
            suite.write_text(json.dumps({"tasks": [{"id": "task-1", "request": "do it", "checks": []}]}))

            def fake_execute(worktree: Path, task: dict, **kwargs) -> dict:
                arm = kwargs["arm"]
                run_dir = worktree / ".proofloop" / "runs" / arm
                (run_dir / "usage").mkdir(parents=True)
                (run_dir / "run.json").write_text("{}\n", encoding="utf-8")
                usage = {
                    "totals": {"rawTotal": 100 if arm.startswith("baseline") else 50, "costUsd": 0.01},
                    "coverage": {"expectedInvocations": 1, "measuredInvocations": 1, "tokenCoverageRatio": 1.0, "costedInvocations": 1},
                }
                return {
                    "verdict": "PROVEN",
                    "agentVerdict": "PROVEN",
                    "runDir": str(run_dir),
                    "durationSeconds": 1,
                    "checks": [],
                    "usage": usage,
                    "usageAvailable": True,
                    "costAvailable": True,
                }

            with patch("proofloop_core.benchmark._execute_trial", side_effect=fake_execute):
                result = run_benchmark(
                    suite,
                    repo,
                    mode="routing",
                    repetitions=1,
                    baseline_host="codex",
                    baseline_model="gpt-test",
                    proofloop_host="codex",
                )

            root = Path(result["benchmarkDir"])
            trials = (root / "trials.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(trials))
            self.assertTrue((root / "comparison.json").exists())
            self.assertEqual([], subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True).stdout.split("worktree ")[2:])


if __name__ == "__main__":
    unittest.main()
