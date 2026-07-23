from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from proofloop_core.assurance.diff_guard import inspect_diff
from proofloop_core.contracts.task_brief import load_task_brief


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def contract_fields() -> dict:
    return {
        "budgets": {"maxFastAttempts": 1, "maxRecoveryAttempts": 0},
        "simplicity": {
            "selectedRung": "DIRECT_CHANGE",
            "rationale": "bounded fixture change",
            "considered": ["REUSE_EXISTING", "STDLIB", "PLATFORM_NATIVE", "INSTALLED_DEPENDENCY"],
            "evidenceRefs": ["fixture#/diff-guard"],
            "permittedNewArtifacts": [],
        },
        "requiredChecks": [{"command": ["python3", "-c", "pass"]}],
    }


class DiffGuardTest(unittest.TestCase):
    def test_scope_and_test_weakening_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests" / "test_app.py").write_text("def test_value():\n    assert 1 == 1\n", encoding="utf-8")
            (root / "config.txt").write_text("safe\n", encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")

            (root / "tests" / "test_app.py").write_text(
                "import pytest\n\n@pytest.mark.skip\ndef test_value():\n    pass\n",
                encoding="utf-8",
            )
            (root / "config.txt").write_text("changed\n", encoding="utf-8")
            task_path = root / ".git" / "proofloop-task.json"
            task_path.write_text(json.dumps({
                "id": "TASK-1",
                "objective": "change app",
                "allowedPaths": ["src/**", "tests/**"],
                "protectedPaths": [],
                "changeBudget": {"maxChangedFiles": 8, "maxAddedLines": 500, "maxNewFiles": 4, "allowDependencyChanges": False},
                **contract_fields(),
            }), encoding="utf-8")
            result = inspect_diff(load_task_brief(task_path), root)
            codes = {item["code"] for item in result["violations"]}
            self.assertEqual("FAIL", result["verdict"])
            self.assertIn("SCOPE_VIOLATION", codes)
            self.assertIn("TEST_DISABLED", codes)
            self.assertIn("ASSERTION_REMOVED", codes)

    def test_change_budget_and_dependency_growth_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init")
            git(root, "config", "user.email", "test@example.com")
            git(root, "config", "user.name", "Test")
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "package.json").write_text('{"dependencies": {}}\n', encoding="utf-8")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")

            (root / "src" / "app.py").write_text("\n".join(f"VALUE_{i} = {i}" for i in range(12)) + "\n", encoding="utf-8")
            (root / "src" / "extra.py").write_text("EXTRA = True\n", encoding="utf-8")
            (root / "package.json").write_text('{"dependencies": {"left-pad": "1.3.0"}}\n', encoding="utf-8")
            task_path = root / ".git" / "proofloop-task.json"
            task_path.write_text(json.dumps({
                "id": "TASK-BLOAT",
                "objective": "small change",
                "allowedPaths": ["src/**", "package.json"],
                "protectedPaths": [],
                "changeBudget": {"maxChangedFiles": 1, "maxAddedLines": 3, "maxNewFiles": 0, "allowDependencyChanges": False},
                **contract_fields(),
            }), encoding="utf-8")
            result = inspect_diff(load_task_brief(task_path), root)
            codes = {item["code"] for item in result["violations"]}
            self.assertIn("CHANGED_FILE_BUDGET_EXCEEDED", codes)
            self.assertIn("ADDED_LINE_BUDGET_EXCEEDED", codes)
            self.assertIn("NEW_FILE_BUDGET_EXCEEDED", codes)
            self.assertIn("DEPENDENCY_CHANGE_FORBIDDEN", codes)
            self.assertIn("UNJUSTIFIED_NEW_ARTIFACT", codes)


if __name__ == "__main__":
    unittest.main()
