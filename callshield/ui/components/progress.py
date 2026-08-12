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
    """Startup checklist: done stages get a right-aligned ``[OK]``.

    The stage currently being probed is shown plainly (no spinner character),
    pending stages are muted. The animation is the *progression* of ``[OK]``
    markers — restrained, readable and truthful: a stage is only marked OK
    after its probe has run.
    """

    width = surface.width if width is None else width
    out: List[str] = []
    marker = "[OK]"
    marker_w = fmt.display_width(marker)
    label_max = max((fmt.display_width(stage) for stage in stages), default=0)
    gutter = min(label_max, max(8, width - marker_w - 3))
    # The marker column sits just past the longest label, so ``[OK]`` stack
    # reads as a column without stretching across the whole terminal.
    marker_col = min(label_max, max(8, width - marker_w - 2)) + 3
    if marker_col + marker_w > width:
        marker_col = max(1, width - marker_w)
    for index, stage in enumerate(stages):
        label = fmt.truncate(stage, gutter)
        if index < completed:
            text = surface.style(fmt.pad(label, marker_col), "muted")
            out.append(text + surface.style(marker, "ok"))
        elif index == completed:
            out.append(surface.style(fmt.pad(label, marker_col), "value"))
        else:
            out.append(surface.style(fmt.pad(label, marker_col), "muted"))
    return out


__all__ = ["Spinner", "progress_bar", "score_meter", "staged_lines"]
