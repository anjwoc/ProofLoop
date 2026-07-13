from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Mapping


LineCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    cwd: str
    exit_code: int
    timed_out: bool
    cancelled: bool
    duration_seconds: float
    stdout_ref: str
    stderr_ref: str


class ProcessRunner:
    def __init__(
        self,
        *,
        terminate_grace_seconds: float = 2.0,
        drain_grace_seconds: float = 2.0,
        poll_interval: float = 0.05,
    ) -> None:
        if terminate_grace_seconds < 0:
            raise ValueError("terminate_grace_seconds must be non-negative")
        if drain_grace_seconds < 0:
            raise ValueError("drain_grace_seconds must be non-negative")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        self.terminate_grace_seconds = terminate_grace_seconds
        self.drain_grace_seconds = drain_grace_seconds
        self.poll_interval = poll_interval

    def run(
        self,
        command: list[str] | tuple[str, ...],
        *,
        cwd: str | Path,
        stdout_path: str | Path,
        stderr_path: str | Path,
        env: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
        on_line: LineCallback | None = None,
        cancel_event: threading.Event | None = None,
    ) -> ProcessResult:
        if not command or not all(isinstance(part, str) and part for part in command):
            raise ValueError("command must be a non-empty sequence of strings")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        root = Path(cwd).resolve()
        stdout_file = Path(stdout_path)
        stderr_file = Path(stderr_path)
        stdout_file.parent.mkdir(parents=True, exist_ok=True)
        stderr_file.parent.mkdir(parents=True, exist_ok=True)
        messages: queue.Queue[tuple[str, str | None, BaseException | None]] = queue.Queue()
        started = time.monotonic()

        with stdout_file.open("wb") as stdout_handle, stderr_file.open("wb") as stderr_handle:
            process = subprocess.Popen(
                list(command),
                cwd=root,
                env=dict(env) if env is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                start_new_session=os.name == "posix",
            )
            assert process.stdout is not None and process.stderr is not None

            threads = [
                threading.Thread(
                    target=self._read_stream,
                    args=("stdout", process.stdout, stdout_handle, messages),
                    daemon=True,
                ),
                threading.Thread(
                    target=self._read_stream,
                    args=("stderr", process.stderr, stderr_handle, messages),
                    daemon=True,
                ),
            ]
            for thread in threads:
                thread.start()

            finished_streams: set[str] = set()
            timed_out = False
            cancelled = False
            termination_started: float | None = None
            kill_started: float | None = None
            killed = False
            pipes_forced_closed = False
            callback_error: BaseException | None = None
            reader_error: BaseException | None = None

            while len(finished_streams) < 2 or process.poll() is None:
                now = time.monotonic()
                if termination_started is None:
                    if cancel_event is not None and cancel_event.is_set():
                        cancelled = True
                        termination_started = now
                        self._terminate(process)
                    elif timeout_seconds is not None and now - started >= timeout_seconds:
                        timed_out = True
                        termination_started = now
                        self._terminate(process)
                elif (
                    not killed
                    and now - termination_started >= self.terminate_grace_seconds
                ):
                    killed = True
                    kill_started = now
                    self._kill(process)
                elif (
                    killed
                    and not pipes_forced_closed
                    and kill_started is not None
                    and now - kill_started >= self.drain_grace_seconds
                    and len(finished_streams) < 2
                ):
                    pipes_forced_closed = True
                    self._close_pipe(process.stdout)
                    self._close_pipe(process.stderr)

                try:
                    stream_name, line, stream_error = messages.get(timeout=self.poll_interval)
                except queue.Empty:
                    continue
                if stream_error is not None:
                    if not pipes_forced_closed and reader_error is None:
                        reader_error = stream_error
                        if termination_started is None:
                            termination_started = time.monotonic()
                            self._terminate(process)
                    continue
                if line is None:
                    finished_streams.add(stream_name)
                    continue
                if on_line is not None and callback_error is None:
                    try:
                        on_line(stream_name, line)
                    except BaseException as exc:
                        callback_error = exc
                        if termination_started is None:
                            termination_started = time.monotonic()
                            self._terminate(process)

            process.wait()
            for thread in threads:
                thread.join(timeout=1)

        if callback_error is not None:
            raise callback_error
        if reader_error is not None:
            raise reader_error
        exit_code = process.returncode
        if timed_out:
            exit_code = 124
        elif cancelled:
            exit_code = 130
        return ProcessResult(
            command=tuple(command),
            cwd=str(root),
            exit_code=exit_code,
            timed_out=timed_out,
            cancelled=cancelled,
            duration_seconds=round(time.monotonic() - started, 6),
            stdout_ref=str(stdout_file),
            stderr_ref=str(stderr_file),
        )

    @staticmethod
    def _read_stream(
        name: str,
        pipe: BinaryIO,
        output: BinaryIO,
        messages: queue.Queue[tuple[str, str | None, BaseException | None]],
    ) -> None:
        try:
            for raw_line in iter(pipe.readline, b""):
                output.write(raw_line)
                output.flush()
                messages.put((name, raw_line.decode("utf-8", errors="replace"), None))
        except BaseException as exc:
            messages.put((name, None, exc))
        finally:
            try:
                pipe.close()
            except OSError:
                pass
            messages.put((name, None, None))

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            pass

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass

    @staticmethod
    def _close_pipe(pipe: BinaryIO | None) -> None:
        if pipe is None:
            return
        try:
            os.close(pipe.fileno())
        except OSError:
            pass
