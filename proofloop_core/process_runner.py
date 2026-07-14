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
HeartbeatCallback = Callable[[int, float], None]


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
        max_queued_lines: int = 1024,
    ) -> None:
        if terminate_grace_seconds < 0:
            raise ValueError("terminate_grace_seconds must be non-negative")
        if drain_grace_seconds < 0:
            raise ValueError("drain_grace_seconds must be non-negative")
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if max_queued_lines <= 0:
            raise ValueError("max_queued_lines must be positive")
        self.terminate_grace_seconds = terminate_grace_seconds
        self.drain_grace_seconds = drain_grace_seconds
        self.poll_interval = poll_interval
        self.max_queued_lines = max_queued_lines

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
        stdin_data: str | bytes | None = None,
        on_heartbeat: HeartbeatCallback | None = None,
        heartbeat_interval_seconds: float = 5.0,
        cancel_event: threading.Event | None = None,
    ) -> ProcessResult:
        if (
            not command
            or not isinstance(command[0], str)
            or not command[0]
            or not all(isinstance(part, str) for part in command)
        ):
            raise ValueError("command must be a non-empty sequence of strings")
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")

        root = Path(cwd).resolve()
        stdout_file = Path(stdout_path)
        stderr_file = Path(stderr_path)
        stdout_file.parent.mkdir(parents=True, exist_ok=True)
        stderr_file.parent.mkdir(parents=True, exist_ok=True)
        messages: queue.Queue[tuple[str, str | None, BaseException | None]] = queue.Queue(
            maxsize=self.max_queued_lines
        )
        stop_readers = threading.Event()
        started = time.monotonic()
        payload = stdin_data.encode("utf-8") if isinstance(stdin_data, str) else stdin_data
        stdin_errors: list[BaseException] = []

        with stdout_file.open("wb") as stdout_handle, stderr_file.open("wb") as stderr_handle:
            process = subprocess.Popen(
                list(command),
                cwd=root,
                env=dict(env) if env is not None else None,
                stdin=subprocess.PIPE if payload is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                start_new_session=os.name == "posix",
            )
            assert process.stdout is not None and process.stderr is not None
            if os.name == "posix":
                os.set_blocking(process.stdout.fileno(), False)
                os.set_blocking(process.stderr.fileno(), False)

            threads = [
                threading.Thread(
                    target=self._read_stream,
                    args=("stdout", process.stdout, stdout_handle, messages, stop_readers, self.poll_interval),
                    daemon=True,
                ),
                threading.Thread(
                    target=self._read_stream,
                    args=("stderr", process.stderr, stderr_handle, messages, stop_readers, self.poll_interval),
                    daemon=True,
                ),
            ]
            for thread in threads:
                thread.start()
            stdin_thread: threading.Thread | None = None
            if payload is not None:
                assert process.stdin is not None
                stdin_thread = threading.Thread(
                    target=self._write_stdin,
                    args=(process.stdin, payload, stdin_errors),
                    daemon=True,
                )
                stdin_thread.start()

            finished_streams: set[str] = set()
            timed_out = False
            cancelled = False
            termination_started: float | None = None
            kill_started: float | None = None
            killed = False
            readers_stopped = False
            callback_error: BaseException | None = None
            reader_error: BaseException | None = None
            next_heartbeat = started + heartbeat_interval_seconds

            while len(finished_streams) < 2 or process.poll() is None:
                now = time.monotonic()
                if (
                    on_heartbeat is not None
                    and callback_error is None
                    and termination_started is None
                    and process.poll() is None
                    and now >= next_heartbeat
                ):
                    try:
                        on_heartbeat(process.pid, now - started)
                    except BaseException as exc:
                        callback_error = exc
                        termination_started = now
                        self._terminate(process)
                    next_heartbeat = now + heartbeat_interval_seconds
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
                    and not readers_stopped
                    and kill_started is not None
                    and now - kill_started >= self.drain_grace_seconds
                    and len(finished_streams) < 2
                ):
                    readers_stopped = True
                    stop_readers.set()

                try:
                    stream_name, line, stream_error = messages.get(timeout=self.poll_interval)
                except queue.Empty:
                    continue
                if stream_error is not None:
                    if not readers_stopped and reader_error is None:
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
            if stdin_thread is not None:
                stdin_thread.join(timeout=1)
            for thread in threads:
                thread.join(timeout=1)

        if callback_error is not None:
            raise callback_error
        if reader_error is not None:
            raise reader_error
        if stdin_errors:
            raise stdin_errors[0]
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
    def _write_stdin(pipe: BinaryIO, payload: bytes, errors: list[BaseException]) -> None:
        try:
            pipe.write(payload)
            pipe.flush()
        except BrokenPipeError:
            pass
        except BaseException as exc:
            errors.append(exc)
        finally:
            try:
                pipe.close()
            except OSError:
                pass

    @staticmethod
    def _read_stream(
        name: str,
        pipe: BinaryIO,
        output: BinaryIO,
        messages: queue.Queue[tuple[str, str | None, BaseException | None]],
        stop_event: threading.Event,
        poll_interval: float,
    ) -> None:
        pending = bytearray()
        try:
            while not stop_event.is_set():
                try:
                    chunk = os.read(pipe.fileno(), 65536)
                except BlockingIOError:
                    stop_event.wait(poll_interval)
                    continue
                if not chunk:
                    break
                output.write(chunk)
                output.flush()
                pending.extend(chunk)
                while b"\n" in pending:
                    boundary = pending.index(b"\n") + 1
                    raw_line = bytes(pending[:boundary])
                    del pending[:boundary]
                    messages.put((name, raw_line.decode("utf-8", errors="replace"), None))
                while len(pending) >= 65536:
                    raw_line = bytes(pending[:65536])
                    del pending[:65536]
                    messages.put((name, raw_line.decode("utf-8", errors="replace"), None))
            if pending:
                messages.put((name, bytes(pending).decode("utf-8", errors="replace"), None))
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
        except (ProcessLookupError, PermissionError):
            pass

    @staticmethod
    def _kill(process: subprocess.Popen[bytes]) -> None:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except (ProcessLookupError, PermissionError):
            pass
