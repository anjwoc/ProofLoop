from __future__ import annotations

class OrchestrationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        verdict: str = "BLOCKED",
        failure_domain: str | None = None,
        questions: tuple[str, ...] = (),
    ):
        super().__init__(message)
        self.code = code
        self.verdict = verdict
        self.failure_domain = failure_domain
        self.questions = questions
