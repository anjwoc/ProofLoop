from __future__ import annotations

class OrchestrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, verdict: str = "BLOCKED"):
        super().__init__(message)
        self.code = code
        self.verdict = verdict
