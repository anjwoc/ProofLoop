import re
from typing import Any

# Match common secret patterns (OpenAI, Anthropic, Gemini, generic tokens)
_SECRET_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9_-]{20,})"),
    re.compile(r"(ghp_[a-zA-Z0-9]{36})"),
    re.compile(r"(AIza[0-9A-Za-z-_]{35})"),
    re.compile(r"(xox[baprs]-[0-9A-Za-z]{10,})"),
]


def redact_secrets(value: Any) -> Any:
    """Recursively redact secrets from a data structure.
    
    ponytail: basic regex over specific keys, covers 99% of accidental logging.
    """
    if isinstance(value, str):
        redacted = value
        for pattern in _SECRET_PATTERNS:
            redacted = pattern.sub("<REDACTED>", redacted)
        return redacted
    if isinstance(value, dict):
        return {k: redact_secrets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    return value
