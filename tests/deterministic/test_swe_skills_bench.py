from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from proofloop_core.cli import main
from proofloop_core.swe_skills_bench import build_swe_suite, inspect_swe_suite


class SweSkillsBenchTest(unittest.TestCase):
    def test_swe_preflight_cli_returns_machine_readable_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            suite = Path(tmp) / "suite.json"
            suite.write_text(json.dumps({"tasks": [{"id": "x", "request": "x", "checks": []}]}))
            output = io.StringIO()
            with patch(
                "proofloop_core.cli.preflight_swe_environment",
                return_value={"schemaVersion": "1.0", "status": "READY", "tasks": []},
            ):
                with redirect_stdout(output):
                    exit_code = main(
                        ["swe-preflight", "--suite", str(suite), "--upstream", tmp, "--docker-binary", "docker"]
                    )

            self.assertEqual(0, exit_code)
            self.assertEqual("READY", json.loads(output.getvalue())["status"])

    def test_imports_pinned_tasks_with_domain_and_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tasks" / "batch1").mkdir(parents=True)
            (root / "tests" / "batch1").mkdir(parents=True)
            (root / "skills" / "api-task").mkdir(parents=True)
            (root / "tasks" / "batch1" / "api-task.md").write_text("# Task\nImplement an API endpoint\n")
            (root / "skills" / "api-task" / "SKILL.md").write_text("# API skill\n")
            (root / "tests" / "batch1" / "test_api_task.py").write_text("def test_api(): pass\n")
            (root / "config").mkdir()
            (root / "config" / "benchmark_config.yaml").write_text("global: {}\n")
            catalog = root / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "upstreamCommit": "a" * 40,
                        "tasks": [
                            {
                                "id": "api-task",
                                "name": "API Task",
                                "domain": "backend",
                                "type": "feature",
                                "repoUrl": "https://example.com/repo.git",
                                "repoCommit": "b" * 40,
                                "dockerImage": "example/image",
                                "checks": [["python", "-m", "pytest", "/workspace/tests/test_api.py"]],
                            }
                        ],
                    }
                )
            )

            suite = build_swe_suite(root, catalog, domains=("backend",))

            self.assertEqual("a" * 40, suite["source"]["commit"])
            self.assertRegex(suite["source"]["configHash"], r"^[0-9a-f]{64}$")
            self.assertEqual("backend", suite["tasks"][0]["domain"])
            self.assertEqual("repo", suite["tasks"][0]["workspaceDirectory"])
            self.assertEqual("Implement an API endpoint", suite["tasks"][0]["request"].splitlines()[-1])
            self.assertRegex(suite["tasks"][0]["skillDocumentHash"], r"^[0-9a-f]{64}$")
            self.assertRegex(suite["tasks"][0]["testDocumentHash"], r"^[0-9a-f]{64}$")

    def test_inspection_requires_backend_frontend_and_devops_coverage(self) -> None:
        suite = {
            "source": {"name": "SWE-Skills-Bench", "commit": "a" * 40},
            "tasks": [
                {"id": "b", "request": "b", "domain": "backend", "checks": []},
                {"id": "f", "request": "f", "domain": "frontend", "checks": []},
                {"id": "d", "request": "d", "domain": "devops", "checks": []},
            ],
        }

        report = inspect_swe_suite(suite)

        self.assertEqual("READY", report["status"])
        self.assertEqual({"backend": 1, "frontend": 1, "devops": 1}, report["domains"])

    def test_inspection_blocks_missing_domain(self) -> None:
        report = inspect_swe_suite(
            {
                "source": {"name": "SWE-Skills-Bench", "commit": "a" * 40},
                "tasks": [{"id": "b", "request": "b", "domain": "backend", "checks": []}],
            }
        )

        self.assertEqual("BLOCKED", report["status"])
        self.assertIn("frontend", report["missingDomains"])


if __name__ == "__main__":
    unittest.main()
