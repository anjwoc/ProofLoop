from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from proofloop_core.process_runner import ProcessRunner


class ProcessRunnerTest(unittest.TestCase):
    def test_line_callback_runs_before_process_exits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arrivals: list[tuple[str, str, float]] = []
            started = time.monotonic()

            result = ProcessRunner().run(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import time; print('first', flush=True); time.sleep(.7); print('last', flush=True)",
                ],
                cwd=root,
                stdout_path=root / "out.log",
                stderr_path=root / "err.log",
                timeout_seconds=3,
                on_line=lambda stream, line: arrivals.append(
                    (stream, line, time.monotonic() - started)
                ),
            )

            self.assertEqual(0, result.exit_code)
            self.assertGreaterEqual(result.duration_seconds, 0.6)
            self.assertEqual("first\n", arrivals[0][1])
            self.assertLess(arrivals[0][2], 0.5)
            self.assertEqual(["first", "last"], (root / "out.log").read_text().splitlines())

    def test_stdout_and_stderr_are_drained_without_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counts = {"stdout": 0, "stderr": 0}

            def count(stream: str, line: str) -> None:
                del line
                counts[stream] += 1

            result = ProcessRunner().run(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    (
                        "import sys\n"
                        "for i in range(2000): print('O' * 80, file=sys.stdout)\n"
                        "for i in range(2000): print('E' * 80, file=sys.stderr)\n"
                    ),
                ],
                cwd=root,
                stdout_path=root / "out.log",
                stderr_path=root / "err.log",
                timeout_seconds=5,
                on_line=count,
            )

            self.assertEqual(0, result.exit_code)
            self.assertEqual({"stdout": 2000, "stderr": 2000}, counts)
            self.assertEqual(2000, len((root / "out.log").read_text().splitlines()))
            self.assertEqual(2000, len((root / "err.log").read_text().splitlines()))

    def test_timeout_preserves_output_and_returns_124(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = ProcessRunner(terminate_grace_seconds=0.1).run(
                [
                    sys.executable,
                    "-u",
                    "-c",
                    "import time; print('before timeout', flush=True); time.sleep(5)",
                ],
                cwd=root,
                stdout_path=root / "out.log",
                stderr_path=root / "err.log",
                timeout_seconds=0.2,
            )

            self.assertTrue(result.timed_out)
            self.assertFalse(result.cancelled)
            self.assertEqual(124, result.exit_code)
            self.assertIn("before timeout", (root / "out.log").read_text())

    def test_cancellation_is_distinct_from_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cancel = threading.Event()
            timer = threading.Timer(0.2, cancel.set)
            timer.start()
            self.addCleanup(timer.cancel)

            result = ProcessRunner(terminate_grace_seconds=0.1).run(
                [sys.executable, "-u", "-c", "import time; time.sleep(5)"],
                cwd=root,
                stdout_path=root / "out.log",
                stderr_path=root / "err.log",
                timeout_seconds=3,
                cancel_event=cancel,
            )

            self.assertFalse(result.timed_out)
            self.assertTrue(result.cancelled)
            self.assertEqual(130, result.exit_code)

    def test_nonzero_exit_code_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = ProcessRunner().run(
                [sys.executable, "-c", "raise SystemExit(7)"],
                cwd=root,
                stdout_path=root / "out.log",
                stderr_path=root / "err.log",
                timeout_seconds=3,
            )
            self.assertEqual(7, result.exit_code)
            self.assertFalse(result.timed_out)
            self.assertFalse(result.cancelled)


if __name__ == "__main__":
    unittest.main()
