import time
from typing import Callable

class VirtualClock:
    def __init__(self, start_time: float = 0.0) -> None:
        self._current_time = start_time
        self._current_monotonic = 0.0
        self._original_time: Callable[[], float] | None = None
        self._original_monotonic: Callable[[], float] | None = None
        self._original_sleep: Callable[[float], None] | None = None

    def tick(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("Cannot tick backward in time.")
        self._current_time += seconds
        self._current_monotonic += seconds

    def patch(self) -> None:
        if self._original_time is not None:
            return  # Already patched
        self._original_time = time.time
        self._original_monotonic = time.monotonic
        self._original_sleep = time.sleep

        time.time = lambda: self._current_time
        time.monotonic = lambda: self._current_monotonic
        # time.sleep in a virtual clock simply advances the clock instantly
        time.sleep = self.tick

    def unpatch(self) -> None:
        if self._original_time is not None:
            time.time = self._original_time
            self._original_time = None
        if self._original_monotonic is not None:
            time.monotonic = self._original_monotonic
            self._original_monotonic = None
        if self._original_sleep is not None:
            time.sleep = self._original_sleep
            self._original_sleep = None
