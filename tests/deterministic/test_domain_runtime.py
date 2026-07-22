from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from proofloop_core.engine.domain_runtime import (
    build_repository_fingerprint,
    run_pack_helper,
    select_reference_slices,
)


class DomainRuntimeTest(unittest.TestCase):
    def test_fingerprint_classifies_generic_workflow_and_detects_framework_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "pyproject.toml").write_text(
                '[project]\nname = "sample"\ndependencies = ["Django==5.1.2"]\n',
                encoding="utf-8",
            )
            (repo / "app.py").write_text("def endpoint(): pass\n", encoding="utf-8")

            fingerprint = build_repository_fingerprint(repo, "Add a backend API endpoint", ("app.py",))

            self.assertIn("backend-development", fingerprint["taskTypes"])
            self.assertEqual("5.1.2", fingerprint["frameworks"]["django"])
            self.assertIn("framework:django", fingerprint["signals"])
            self.assertNotIn("django", fingerprint["taskTypes"])

    def test_reference_selection_loads_common_and_matching_adapter_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "pack"
            (pack / "adapters").mkdir(parents=True)
            (pack / "references").mkdir()
            (pack / "adapters" / "index.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "adapters": [
                            {"id": "django", "signals": ["framework:django"], "framework": {"name": "django", "range": ">=5 <6"}},
                            {"id": "spring", "signals": ["framework:spring"], "framework": {"name": "spring", "range": ">=3 <4"}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (pack / "references" / "index.json").write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "slices": [
                            {"id": "common", "path": "references/common.md", "always": True, "estimatedTokens": 100},
                            {"id": "django", "path": "references/django.md", "adapter": "django", "estimatedTokens": 120},
                            {"id": "spring", "path": "references/spring.md", "adapter": "spring", "estimatedTokens": 130},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            for name in ("common", "django", "spring"):
                (pack / "references" / f"{name}.md").write_text(name, encoding="utf-8")

            selection = select_reference_slices(
                pack,
                {
                    "signals": ["framework:django"],
                    "frameworks": {"django": "5.1.2"},
                    "taskTypes": ["backend-development"],
                },
                max_tokens=500,
            )

            self.assertEqual(["django"], selection["adapters"])
            self.assertEqual(["common", "django"], [item["id"] for item in selection["slices"]])
            self.assertEqual(220, selection["estimatedTokens"])
            self.assertNotIn("spring", json.dumps(selection))

    def test_reference_selection_rejects_path_escape_and_budget_overrun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = root / "pack"
            (pack / "references").mkdir(parents=True)
            outside = root / "outside.md"
            outside.write_text("outside", encoding="utf-8")
            index = pack / "references" / "index.json"
            index.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "slices": [{"id": "escape", "path": "../outside.md", "always": True, "estimatedTokens": 10}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "escapes pack root"):
                select_reference_slices(pack, {"signals": [], "frameworks": {}, "taskTypes": []}, max_tokens=100)

            (pack / "references" / "large.md").write_text("large", encoding="utf-8")
            index.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "slices": [{"id": "large", "path": "references/large.md", "always": True, "estimatedTokens": 101}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "context budget"):
                select_reference_slices(pack, {"signals": [], "frameworks": {}, "taskTypes": []}, max_tokens=100)

    def test_helper_runs_without_shell_and_parent_materializes_json_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pack = root / "pack"
            repo = root / "repo"
            run_dir = root / "run"
            (pack / "scripts").mkdir(parents=True)
            repo.mkdir()
            helper = pack / "scripts" / "probe"
            helper.write_text(
                "#!/usr/bin/env python3\n"
                "import argparse, json\n"
                "p=argparse.ArgumentParser(); p.add_argument('--repo', required=True); a=p.parse_args()\n"
                "print(json.dumps({'schemaVersion':'1.0','repo':a.repo,'verdict':'PASS'}))\n",
                encoding="utf-8",
            )
            helper.chmod(0o755)
            output = run_dir / "probe.json"

            result = run_pack_helper(pack, "scripts/probe", repo, output, timeout_seconds=5)

            self.assertEqual("PARENT_PROCESS", result["artifactOwner"])
            artifact = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("PASS", artifact["verdict"])
            self.assertEqual(str(repo.resolve()), artifact["repo"])

    def test_fingerprint_detects_test_and_frontend_adapters_without_promoting_them_to_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "package.json").write_text(
                json.dumps(
                    {
                        "name": "ui",
                        "dependencies": {"react": "^18.3.1"},
                        "devDependencies": {"jest": "^29.7.0"},
                        "scripts": {"test": "jest"},
                    }
                ),
                encoding="utf-8",
            )

            fingerprint = build_repository_fingerprint(repo, "Add frontend component tests")

            self.assertIn("frontend-development", fingerprint["taskTypes"])
            self.assertIn("test-engineering", fingerprint["taskTypes"])
            self.assertEqual("18.3.1", fingerprint["frameworks"]["react"])
            self.assertEqual("29.7.0", fingerprint["frameworks"]["jest"])
            self.assertIn("framework:jest", fingerprint["signals"])
            self.assertNotIn("jest", fingerprint["taskTypes"])


if __name__ == "__main__":
    unittest.main()
