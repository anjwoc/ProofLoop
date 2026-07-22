from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from proofloop_core.analysis.benchmark_environment import (
    SWETrialEnvironment,
    materialize_repository,
    parse_test_output,
    preflight_swe_environment,
)


def git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=repository, text=True, capture_output=True, check=True
    )
    return completed.stdout.strip()


class BenchmarkEnvironmentTest(unittest.TestCase):
    def test_parse_test_output_reports_partial_pytest_success(self) -> None:
        parsed = parse_test_output(
            "================ 3 passed, 2 failed, 1 skipped in 1.25s ================\n",
            exit_code=1,
        )

        self.assertEqual(6, parsed["testsTotal"])
        self.assertEqual(3, parsed["testsPassed"])
        self.assertEqual(2, parsed["testsFailed"])
        self.assertEqual(1, parsed["testsSkipped"])
        self.assertEqual(0.5, parsed["testPassRate"])
        self.assertFalse(parsed["taskPassed"])

    def test_materialize_repository_checks_out_exact_catalog_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            git(source, "init")
            git(source, "config", "user.email", "proofloop@example.invalid")
            git(source, "config", "user.name", "ProofLoop Test")
            (source / "value.txt").write_text("pinned\n", encoding="utf-8")
            git(source, "add", "value.txt")
            git(source, "commit", "-m", "pinned")
            pinned = git(source, "rev-parse", "HEAD")
            (source / "value.txt").write_text("later\n", encoding="utf-8")
            git(source, "commit", "-am", "later")

            target = root / "trial"
            observed = materialize_repository(
                {"repository": {"url": str(source), "commit": pinned}}, target
            )

            self.assertEqual(target.resolve(), observed)
            self.assertEqual(pinned, git(target, "rev-parse", "HEAD"))
            self.assertEqual("pinned\n", (target / "value.txt").read_text(encoding="utf-8"))

    def test_preflight_verifies_upstream_commit_hashes_and_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = root / "upstream"
            (upstream / "tests" / "batch1").mkdir(parents=True)
            (upstream / "skills" / "sample").mkdir(parents=True)
            (upstream / "tests" / "batch1" / "test_sample.py").write_text("def test_ok(): pass\n", encoding="utf-8")
            (upstream / "skills" / "sample" / "SKILL.md").write_text("# Sample\n", encoding="utf-8")
            git(upstream, "init")
            git(upstream, "config", "user.email", "proofloop@example.invalid")
            git(upstream, "config", "user.name", "ProofLoop Test")
            git(upstream, "add", ".")
            git(upstream, "commit", "-m", "fixture")
            commit = git(upstream, "rev-parse", "HEAD")
            docker = self._fake_docker(root, pytest_output="1 passed in 0.01s")
            suite = self._suite(upstream, commit)

            report = preflight_swe_environment(suite, upstream, docker_binary=str(docker))

            self.assertEqual("READY", report["status"])
            self.assertEqual(commit, report["source"]["observedCommit"])
            self.assertEqual("AVAILABLE", report["images"]["proofloop/test:latest"])
            task = report["tasks"][0]
            self.assertEqual("READY", task["status"])
            self.assertEqual(64, len(task["testHash"]))
            self.assertEqual(64, len(task["skillHash"]))

    def test_docker_evaluator_mounts_official_test_read_only_and_preserves_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            upstream = root / "upstream"
            test_path = upstream / "tests" / "batch1" / "test_sample.py"
            test_path.parent.mkdir(parents=True)
            test_path.write_text("def test_ok(): pass\n", encoding="utf-8")
            (test_path.parent / "_dependency_utils.py").write_text("# shared evaluator helper\n", encoding="utf-8")
            (upstream / "skills" / "sample").mkdir(parents=True)
            (upstream / "skills" / "sample" / "SKILL.md").write_text("# Sample\n", encoding="utf-8")
            repository = root / "repo"
            repository.mkdir()
            docker = self._fake_docker(root, pytest_output="2 passed, 1 failed in 0.02s")
            task = self._suite(upstream, "0" * 40)["tasks"][0]
            before = test_path.read_bytes()

            result = SWETrialEnvironment(upstream, docker_binary=str(docker)).evaluate(
                task, repository=repository, timeout_seconds=30
            )

            self.assertFalse(result["taskPassed"])
            self.assertEqual(3, result["testsTotal"])
            self.assertEqual(2, result["testsPassed"])
            self.assertEqual(2 / 3, result["testPassRate"])
            self.assertEqual("PASS", result["protectedTestIntegrity"])
            self.assertEqual(before, test_path.read_bytes())
            calls = [json.loads(line) for line in (root / "docker-calls.jsonl").read_text(encoding="utf-8").splitlines()]
            run_call = next(call for call in calls if call[:1] == ["run"])
            self.assertIn(
                f"type=bind,source={test_path.parent.resolve()},target=/workspace/tests,readonly",
                run_call,
            )
            self.assertTrue(any("target=/workspace/sample" in argument for argument in run_call))
            self.assertIn("/workspace/sample", run_call)
            self.assertIn("/workspace/tests/test_sample.py", run_call)

    def _fake_docker(self, root: Path, *, pytest_output: str) -> Path:
        docker = root / "docker"
        docker.write_text(
            "#!/usr/bin/env python3\n"
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "log = Path(os.environ['FAKE_DOCKER_LOG'])\n"
            "with log.open('a') as handle: handle.write(json.dumps(sys.argv[1:]) + '\\n')\n"
            "args = sys.argv[1:]\n"
            "if args[:1] == ['info']: print('29.5.3')\n"
            "elif args[:2] == ['image', 'inspect']: print('sha256:fixture')\n"
            "elif args[:1] == ['run']: print(os.environ['FAKE_PYTEST_OUTPUT']); sys.exit(int(os.environ.get('FAKE_TEST_EXIT', '1')))\n"
            "else: sys.exit(2)\n",
            encoding="utf-8",
        )
        docker.chmod(0o755)
        os.environ["FAKE_DOCKER_LOG"] = str(root / "docker-calls.jsonl")
        os.environ["FAKE_PYTEST_OUTPUT"] = pytest_output
        os.environ["FAKE_TEST_EXIT"] = "1" if "failed" in pytest_output else "0"
        return docker

    def _suite(self, upstream: Path, commit: str) -> dict:
        return {
            "schemaVersion": "1.0",
            "source": {"name": "SWE-Skills-Bench", "commit": commit},
            "tasks": [
                {
                    "id": "sample",
                    "request": "Implement sample",
                    "domain": "backend",
                    "repository": {"url": str(upstream), "commit": commit},
                    "workspaceDirectory": "sample",
                    "dockerImage": "proofloop/test:latest",
                    "upstreamTest": "tests/batch1/test_sample.py",
                    "skillDocument": "skills/sample/SKILL.md",
                    "checks": [["python", "-m", "pytest", "/workspace/tests/test_sample.py", "-q"]],
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
