from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from threading import Lock


class IdempotencyExecutor:
    def __init__(self) -> None:
        self._results: dict[str, Future[str]] = {}
        self._lock = Lock()

    def execute(self, key: str, operation: Callable[[], str]) -> str:
        # BUG: the check and insertion are not atomic, so concurrent callers can
        # execute the operation more than once for the same key.
        if key not in self._results:
            future: Future[str] = Future()
            self._results[key] = future
            try:
                future.set_result(operation())
            except BaseException as error:
                future.set_exception(error)
                self._results.pop(key, None)
                raise
        return self._results[key].result()
