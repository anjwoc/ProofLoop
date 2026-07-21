from __future__ import annotations

from typing import Any, Protocol, TextIO

from .human import HumanRenderer
from .jsonl import JsonlRenderer
from .quiet import QuietRenderer


class Renderer(Protocol):
    def render(self, event: dict[str, Any]) -> None: ...


def build_renderer(
    output_format: str,
    stream: TextIO,
    verbosity: str = "info",
    color: str = "auto",
) -> Renderer:
    if output_format == "human":
        return HumanRenderer(stream, verbosity=verbosity, color=color)
    if output_format == "jsonl":
        return JsonlRenderer(stream)
    if output_format == "quiet":
        return QuietRenderer()
    if output_format == "tui":
        from ..tui import TuiRenderer

        return TuiRenderer(stream)
    raise ValueError(f"unsupported output format: {output_format}")


__all__ = ["Renderer", "build_renderer"]
