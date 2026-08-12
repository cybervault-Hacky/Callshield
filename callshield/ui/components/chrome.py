"""Application chrome: header, breadcrumb, status bar, footer, notices."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

from .. import formatters as fmt
from .base import Surface
from .panel import rule


def header(
    surface: Surface,
    title: str,
    subtitle: str = "",
    version: str = "",
    width: Optional[int] = None,
) -> List[str]:
    """Product header. Two lines on normal terminals, one when narrow."""

    width = surface.width if width is None else width
    left = surface.style(fmt.truncate(title, max(8, width - 12)), "brand")
    right = surface.style(version, "muted") if version else ""
    gap = max(1, width - fmt.display_width(left) - fmt.display_width(right))
    out = [left + " " * gap + right]
    if subtitle and not surface.narrow:
        out.append(surface.style(fmt.truncate(subtitle, width), "muted"))
    out.append(rule(surface, width))
    return out


def breadcrumb(surface: Surface, trail: Sequence[str],
               width: Optional[int] = None) -> str:
    width = surface.width if width is None else width
    arrow = " {0} ".format(surface.glyph("arrow"))
    text = arrow.join(str(part) for part in trail if str(part))
    return surface.style(fmt.truncate(text, width), "muted")


def status_bar(
    surface: Surface,
    fields: Sequence[Tuple[str, Any]],
    width: Optional[int] = None,
) -> List[str]:
    """A compact ``LABEL VALUE`` strip; wraps onto extra lines when needed."""

    width = surface.width if width is None else width
    separator = "  {0}  ".format(surface.glyph("v"))
    chunks: List[str] = []
    for label, value in fields:
        word = fmt.status_word(value)
        chunks.append(
            surface.style(str(label), "label") + " " + surface.status(word)
        )

    lines: List[str] = []
    current = ""
    for chunk in chunks:
        candidate = chunk if not current else current + separator + chunk
        if fmt.display_width(fmt.strip_ansi(candidate)) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = chunk
    if current:
        lines.append(current)
    return lines


def notice(surface: Surface, message: str, level: str = "info",
           width: Optional[int] = None) -> List[str]:
    """An inline message. The level word is printed, never just coloured."""

    width = surface.width if width is None else width
    words = {"info": "NOTE", "warn": "WARNING", "err": "ERROR", "ok": "OK"}
    role = level if level in ("info", "warn", "err", "ok") else "info"
    tag = words.get(role, "NOTE")
    body = "{0}: {1}".format(tag, message)
    return [surface.style(line, role) for line in fmt.wrap(body, width)]


def footer(
    surface: Surface,
    hints: Sequence[str],
    width: Optional[int] = None,
    message: str = "",
) -> List[str]:
    """Key hints. Always shows how to go back and how to quit."""

    width = surface.width if width is None else width
    out = [rule(surface, width)]
    if message:
        out.extend(notice(surface, message, "info", width))
    text = surface.glyph("bullet").join(
        " {0} ".format(hint) for hint in hints if hint
    ).strip()
    for line in fmt.wrap(text, width):
        out.append(surface.style(line, "muted"))
    return out


def confirm_line(surface: Surface, question: str, default_no: bool = True) -> str:
    """Render a destructive-action prompt with an explicit default."""

    suffix = " [y/N] " if default_no else " [Y/n] "
    return surface.style(question + suffix, "warn")


__all__ = [
    "breadcrumb",
    "confirm_line",
    "footer",
    "header",
    "notice",
    "status_bar",
]
