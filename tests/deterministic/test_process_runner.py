from __future__ import annotations

import os
import signal
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

    @unittest.skipUnless(os.name == "posix", "process-group semantics require POSIX")
    def test_timeout_kills_descendant_that_keeps_pipes_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pid_path = root / "leader.pid"
            holder: dict[str, object] = {}
            script = (
                "import os, signal, subprocess, sys, time\n"
                f"open({str(pid_path)!r}, 'w').write(str(os.getpid()))\n"
                "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
                "subprocess.Popen([sys.executable, '-c', "
                "'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)'])\n"
                "print('leader-ready', flush=True)\n"
                "time.sleep(30)\n"
            )

            def execute() -> None:
                try:
                    holder["result"] = ProcessRunner(terminate_grace_seconds=0.1).run(
                        [sys.executable, "-u", "-c", script],
                        cwd=root,
                        stdout_path=root / "out.log",
                        stderr_path=root / "err.log",
                        timeout_seconds=0.2,
                    )
                except BaseException as exc:
                    holder["error"] = exc

            thread = threading.Thread(target=execute, daemon=True)
            thread.start()
            thread.join(timeout=1.5)
            was_stuck = thread.is_alive()
            if was_stuck and pid_path.exists():
                os.killpg(int(pid_path.read_text(encoding="utf-8")), signal.SIGKILL)
                thread.join(timeout=2)

            self.assertFalse(was_stuck, "timeout left a descendant holding stdout/stderr open")
            self.assertNotIn("error", holder)
            result = holder["result"]
            self.assertEqual(124, result.exit_code)  # type: ignore[union-attr]

    def test_invalid_utf8_is_preserved_in_raw_log_and_replaced_for_callback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            arrivals: list[str] = []
            result = ProcessRunner().run(
                [sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'before\\xffafter\\n'); sys.stdout.flush()"],
                cwd=root,
                stdout_path=root / "out.log",
                stderr_path=root / "err.log",
                timeout_seconds=3,
                on_line=lambda _stream, line: arrivals.append(line),
            )

            self.assertEqual(0, result.exit_code)
            self.assertEqual(b"before\xffafter\n", (root / "out.log").read_bytes())
            self.assertEqual(["before\ufffdafter\n"], arrivals)

    @unittest.skipUnless(os.name == "posix", "detached descendant semantics require POSIX")
    def test_timeout_has_a_real_drain_deadline_for_detached_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child_pid_path = root / "child.pid"
            holder: dict[str, object] = {}
            child_script = (
                "import os, signal, time\n"
                f"open({str(child_pid_path)!r}, 'w').write(str(os.getpid()))\n"
                "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                "time.sleep(30)\n"
            )
            leader_script = (
                "import subprocess, sys, time\n"
                f"subprocess.Popen([sys.executable, '-c', {child_script!r}], start_new_session=True)\n"
                "print('leader-ready', flush=True)\n"
                "time.sleep(30)\n"
            )

            def execute() -> None:
                try:
                    holder["result"] = ProcessRunner(
                        terminate_grace_seconds=0.1,
                        drain_grace_seconds=0.1,
                    ).run(
                        [sys.executable, "-u", "-c", leader_script],
                        cwd=root,
                        stdout_path=root / "out.log",
                        stderr_path=root / "err.log",
                        timeout_seconds=0.2,
                    )
                except BaseException as exc:
                    holder["error"] = exc

            thread = threading.Thread(target=execute, daemon=True)
            thread.start()
            thread.join(timeout=1.5)
            was_stuck = thread.is_alive()
            if child_pid_path.exists():
                try:
                    os.kill(int(child_pid_path.read_text(encoding="utf-8")), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            thread.join(timeout=2)

            self.assertFalse(was_stuck, "drain deadline did not release detached descendant pipes")
            self.assertNotIn("error", holder)
            result = holder["result"]
            self.assertEqual(124, result.exit_code)  # type: ignore[union-attr]

    def test_output_queue_capacity_is_explicitly_bounded(self) -> None:
        runner = ProcessRunner(max_queued_lines=8)
        self.assertEqual(8, runner.max_queued_lines)


if __name__ == "__main__":
    unittest.main()
