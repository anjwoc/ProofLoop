from __future__ import annotations

from .antigravity import AntigravityOutputParser
from .base import HostOutputParser, NormalizedHostEvent
from .claude import ClaudeOutputParser
from .codex import CodexOutputParser


def parser_for(host: str) -> HostOutputParser:
    if host == "codex":
        return CodexOutputParser()
    if host == "antigravity":
        return AntigravityOutputParser()
    if host == "claude-code":
        return ClaudeOutputParser()
    raise ValueError(f"unsupported host parser: {host}")


__all__ = ["HostOutputParser", "NormalizedHostEvent", "parser_for"]
