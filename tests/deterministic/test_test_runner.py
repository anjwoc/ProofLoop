from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def _load_runner():
    path = ROOT / "scripts" / "run_tests.py"
    spec = importlib.util.spec_from_file_location("proofloop_test_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scripts/run_tests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestRunnerTest(unittest.TestCase):
    def test_official_runner_uses_pytest_for_both_suites(self) -> None:
        runner = _load_runner()

        with patch.object(runner.pytest, "main", return_value=0) as pytest_main:
            self.assertEqual(0, runner.main())

        pytest_main.assert_called_once_with(
            [
                str(ROOT / "tests" / "deterministic"),
                str(ROOT / "tests" / "orchestration"),
                "-q",
            ]
        )


if __name__ == "__main__":
    unittest.main()
