"""Spinner, progress bar and score meter.

None of these sleep or drive the clock themselves; the caller advances the tick
so the UI can stay non-blocking and animation can be switched off entirely.
"""

from __future__ import annotations

from typing import List, Optional

from .. import formatters as fmt
from .base import Surface


class Spinner:
    """Frame counter for an indeterminate activity indicator."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = bool(enabled)
        self.tick = 0

    def advance(self) -> None:
        self.tick += 1

    def frame(self, surface: Surface) -> str:
        if not self.enabled:
            return surface.glyph("bullet")
        return surface.glyphs.spinner_frame(self.tick)


def progress_bar(
    surface: Surface,
    done: int,
    total: int,
    width: Optional[int] = None,
    show_counts: bool = True,
) -> str:
    """Determinate progress bar; renders as text when the space is tiny."""

    width = surface.width if width is None else width
    total = max(1, int(total or 1))
    done = max(0, min(int(done or 0), total))
    counts = " {0}/{1}".format(done, total) if show_counts else ""
    bar_width = max(4, width - fmt.display_width(counts) - 2)
    filled = int(round(bar_width * (done / float(total))))
    body = (surface.glyph("bar_full") * filled
            + surface.glyph("bar_empty") * (bar_width - filled))
    return surface.style("[", "border") + surface.style(body, "accent") \
        + surface.style("]", "border") + surface.style(counts, "muted")


def score_meter(
    surface: Surface,
    value,
    width: Optional[int] = None,
    label: str = "",
    level: str = "",
) -> str:
    """Risk/confidence meter: bar plus the numeric value plus the level word."""

    width = surface.width if width is None else width
    text = fmt.score(value)
    if text == fmt.PLACEHOLDER:
        return surface.style("{0} {1}".format(label, fmt.PLACEHOLDER).strip(), "muted")

    suffix = " {0}".format(fmt.pad(text, 3, "right"))
    if level:
        suffix += "  " + surface.status(level)
    prefix = (label + " ") if label else ""
    room = width - fmt.display_width(prefix) - fmt.display_width(fmt.strip_ansi(suffix))
    bar_width = max(4, min(28, room - 2))
    body = fmt.bar(value, bar_width, surface.glyph("bar_full"),
                   surface.glyph("bar_empty"))
    return (surface.style(prefix, "label") + surface.style("[", "border")
            + body + surface.style("]", "border") + suffix)


def staged_lines(
    surface: Surface,
    stages: List[str],
    completed: int,
    spinner: Optional[Spinner] = None,
    width: Optional[int] = None,
) -> List[str]:
    """Startup checklist: done stages keep a marker, the current one spins."""

    width = surface.width if width is None else width
    out: List[str] = []
    done_mark = surface.glyph("bullet")
    for index, stage in enumerate(stages):
        if index < completed:
            mark = surface.style(done_mark, "ok")
            text = surface.style(stage, "muted")
        elif index == completed:
            frame = spinner.frame(surface) if spinner else done_mark
            mark = surface.style(frame, "accent")
            text = surface.style(stage, "value")
        else:
            mark = " "
            text = surface.style(stage, "muted")
        out.append(fmt.truncate("{0} {1}".format(mark, text), width))
    return out


__all__ = ["Spinner", "progress_bar", "score_meter", "staged_lines"]
