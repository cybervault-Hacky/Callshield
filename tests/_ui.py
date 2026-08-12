"""Shared helpers for the Phase 8.5 terminal interface tests.

The interface is tested head-less: a :class:`Capabilities` snapshot replaces the
real terminal probe, output goes to a ``StringIO`` and prompts are scripted, so
no test needs a TTY, a daemon or a network.
"""

from __future__ import annotations

import io
from typing import Any, List, Optional, Sequence

from callshield.ui.app import AppContext, Application
from callshield.ui.theme import Capabilities


def caps(width: int = 100, height: int = 32, color: bool = False,
         unicode: bool = False, interactive: bool = False) -> Capabilities:
    return Capabilities(
        width=width,
        height=height,
        color=color,
        unicode=unicode,
        interactive=interactive,
    )


class ScriptedContext(AppContext):
    """Application context whose prompts are answered from a script."""

    def __init__(self, cfg: Any, *, answers: Optional[Sequence[Any]] = None,
                 **kwargs: Any) -> None:
        kwargs.setdefault("stdout", io.StringIO())
        kwargs.setdefault("caps", caps())
        AppContext.__init__(self, cfg, **kwargs)
        self.answers: List[Any] = list(answers or [])
        self.asked: List[str] = []
        self.terminal_calls: List[str] = []

    # ------------------------------------------------------------- prompting
    def ask(self, prompt: str) -> Optional[str]:
        self.asked.append(str(prompt))
        if not self.answers:
            return None
        value = self.answers.pop(0)
        if value is None:
            return None
        if isinstance(value, BaseException):
            raise value
        return str(value)

    def confirm(self, question: str) -> bool:
        answer = self.ask(question)
        if not answer:
            return False
        return answer.strip().lower() in ("y", "yes")

    def run_with_terminal(self, action, notice: str = ""):
        self.terminal_calls.append(str(notice))
        return action()

    # ---------------------------------------------------------------- output
    @property
    def written(self) -> str:
        return self.stdout.getvalue()


def make_app(cfg: Any, screen_key: str = "dashboard", **kwargs: Any):
    """Build a context plus an :class:`Application` rooted at ``screen_key``."""

    ctx = ScriptedContext(cfg, **kwargs)
    app = Application(ctx)
    app.start(ctx.make_screen(screen_key))
    return ctx, app


def plain(lines: Sequence[str]) -> str:
    """Join rendered lines with ANSI styling removed."""

    from callshield.ui import formatters as fmt

    return "\n".join(fmt.strip_ansi(line) for line in lines)


def render(app: Application) -> str:
    return plain(app.render())


__all__ = [
    "EMOJI_RANGES",
    "ScriptedContext",
    "caps",
    "emoji_characters",
    "make_app",
    "plain",
    "render",
]


# Codepoint ranges that carry pictographic/emoji characters. Box drawing
# (U+2500..U+257F) and CJK text are deliberately excluded.
EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0xFE00, 0xFE0F),
    (0x1F1E6, 0x1F1FF),
    (0x2190, 0x21FF),
)


def emoji_characters(text: str):
    """Return any pictographic characters found in ``text``."""

    found = []
    for char in str(text):
        point = ord(char)
        for low, high in EMOJI_RANGES:
            if low <= point <= high:
                found.append(char)
                break
    return found
