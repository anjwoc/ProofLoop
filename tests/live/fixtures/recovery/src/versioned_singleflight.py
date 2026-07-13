from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from threading import Lock


class VersionedSingleFlight:
    """Deduplicate operations per key while supporting invalidation."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._versions: dict[str, int] = {}
        self._inflight: dict[tuple[str, int], Future[str]] = {}
        self._cache: dict[tuple[str, int], str] = {}

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._versions[key] = self._versions.get(key, 0) + 1

    def execute(self, key: str, operation: Callable[[], str]) -> str:
        # BUGS: ownership is not atomic, failures remain in _inflight, and a
        # stale generation can be cached after invalidate().
        version = self._versions.get(key, 0)
        token = (key, version)
        if token in self._cache:
            return self._cache[token]
        future = self._inflight.get(token)
        if future is None:
            future = Future()
            self._inflight[token] = future
            try:
                value = operation()
                self._cache[token] = value
                future.set_result(value)
            except BaseException as error:
                future.set_exception(error)
                raise
        return future.result()
