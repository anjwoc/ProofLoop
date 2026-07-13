from __future__ import annotations

import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.idempotency import IdempotencyExecutor


class IdempotencyExecutorTest(unittest.TestCase):
    def test_concurrent_same_key_runs_operation_once(self) -> None:
        executor = IdempotencyExecutor()
        calls = 0
        lock = Lock()

        def operation() -> str:
            nonlocal calls
            time.sleep(0.02)
            with lock:
                calls += 1
            return "ok"

        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: executor.execute("same", operation), range(50)))
        self.assertEqual(["ok"] * 50, results)
        self.assertEqual(1, calls)

    def test_failed_operation_is_not_cached(self) -> None:
        executor = IdempotencyExecutor()
        attempts = 0

        def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary")
            return "ok"

        with self.assertRaises(RuntimeError):
            executor.execute("retry", operation)
        self.assertEqual("ok", executor.execute("retry", operation))
        self.assertEqual(2, attempts)


if __name__ == "__main__":
    unittest.main()
