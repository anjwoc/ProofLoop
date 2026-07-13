from __future__ import annotations

import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.versioned_singleflight import VersionedSingleFlight


class VersionedSingleFlightTest(unittest.TestCase):
    def test_same_generation_executes_once(self) -> None:
        subject = VersionedSingleFlight()
        calls = 0
        lock = Lock()

        def operation() -> str:
            nonlocal calls
            time.sleep(0.02)
            with lock:
                calls += 1
            return "v1"

        with ThreadPoolExecutor(max_workers=20) as pool:
            values = list(pool.map(lambda _: subject.execute("a", operation), range(40)))
        self.assertEqual(["v1"] * 40, values)
        self.assertEqual(1, calls)

    def test_failure_is_not_cached_or_left_inflight(self) -> None:
        subject = VersionedSingleFlight()
        attempts = 0

        def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary")
            return "ok"

        with self.assertRaises(RuntimeError):
            subject.execute("a", operation)
        self.assertEqual("ok", subject.execute("a", operation))
        self.assertEqual(2, attempts)

    def test_invalidation_separates_generations_and_stale_result_is_not_reused(self) -> None:
        subject = VersionedSingleFlight()
        started = Event()
        release = Event()

        def old_operation() -> str:
            started.set()
            release.wait(timeout=2)
            return "old"

        with ThreadPoolExecutor(max_workers=2) as pool:
            old = pool.submit(subject.execute, "a", old_operation)
            self.assertTrue(started.wait(timeout=1))
            subject.invalidate("a")
            new = pool.submit(subject.execute, "a", lambda: "new")
            self.assertEqual("new", new.result(timeout=1))
            release.set()
            self.assertEqual("old", old.result(timeout=1))
        self.assertEqual("new", subject.execute("a", lambda: "must-not-run"))

    def test_different_keys_can_progress_independently(self) -> None:
        subject = VersionedSingleFlight()
        barrier = Event()

        def slow() -> str:
            barrier.wait(timeout=1)
            return "slow"

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(subject.execute, "slow", slow)
            second = pool.submit(subject.execute, "fast", lambda: "fast")
            self.assertEqual("fast", second.result(timeout=0.5))
            barrier.set()
            self.assertEqual("slow", first.result(timeout=1))


if __name__ == "__main__":
    unittest.main()
