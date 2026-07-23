"""Deterministic fault points for ProofLoop resilience tests."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from typing import Any


class ChaosInjectionError(RuntimeError):
    """Raised when an explicitly selected test fault point is reached."""


class ChaosController:
    """Inject named failures deterministically; never sleep or kill a process."""

    def __init__(self, faults: Iterable[str] = ()) -> None:
        configured = os.environ.get("PROOFLOOP_CHAOS_FAULTS", "")
        self.faults = frozenset({*faults, *(item.strip() for item in configured.split(",") if item.strip())})
        self.triggered: list[str] = []

    def inject(self, point: str) -> None:
        if point in self.faults:
            self.triggered.append(point)
            raise ChaosInjectionError(f"Injected ProofLoop fault: {point}")

    def inject_network_latency(self) -> None:
        self.inject("network_latency")

    def inject_process_kill(self, pid: int) -> None:
        del pid
        self.inject("process_kill")

    def inject_token_limit(self) -> None:
        self.inject("token_limit")

    def execute_with_chaos(self, name: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        self.inject(name)
        return func(*args, **kwargs)
