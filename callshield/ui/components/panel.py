"""Panels, rules and key/value rows."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple

from .. import formatters as fmt
from .base import Surface


def rule(surface: Surface, width: Optional[int] = None, role: str = "border") -> str:
    width = surface.width if width is None else width
    return surface.style(surface.glyph("h") * max(1, width), role)


def section_title(surface: Surface, title: str, width: Optional[int] = None) -> str:
    """A quiet section header: just the uppercase label, no ruling.

    Hierarchy comes from spacing and the label weight, not from a line of
    dashes after every heading.
    """

    width = surface.width if width is None else width
    label = fmt.truncate(str(title).upper(), max(4, width))
    return surface.style(label, "title")


def card(
    surface: Surface,
    lines: Sequence[str],
    title: str = "",
    width: Optional[int] = None,
    footer: str = "",
) -> List[str]:
    """A bordered card used for focused results (scan, reputation, policy).

    The border is drawn in the subtle border colour and never contains colour
    itself; content keeps its own semantic styling.
    """

    width = surface.width if width is None else width
    width = max(12, min(width, surface.width))
    g = surface.glyphs
    inner = width - 4
    out: List[str] = []

    if title:
        label = " " + fmt.truncate(str(title), max(1, inner)) + " "
        bar = g["h"] * max(0, width - 2 - fmt.display_width(label))
        out.append(surface.style(g["tl"] + label + bar + g["tr"], "border"))
    else:
        out.append(surface.style(g["tl"] + g["h"] * (width - 2) + g["tr"], "border"))

    edge = surface.style(g["v"], "border")
    for line in lines:
        text = "" if line is None else str(line)
        out.append(edge + " " + fmt.pad(text, inner) + " " + edge)

    if footer:
        label = " " + fmt.truncate(str(footer), max(1, inner)) + " "
        bar = g["h"] * max(0, width - 2 - fmt.display_width(label))
        out.append(surface.style(g["bl"] + bar + label + g["br"], "border"))
    else:
        out.append(surface.style(g["bl"] + g["h"] * (width - 2) + g["br"], "border"))
    return out


def panel(
    surface: Surface,
    lines: Sequence[str],
    title: str = "",
    width: Optional[int] = None,
    footer: str = "",
) -> List[str]:
    """Draw a bordered box around ``lines``."""

    width = surface.width if width is None else width
    width = max(12, width)
    g = surface.glyphs
    inner = width - 4
    out: List[str] = []

    if title:
        label = " " + fmt.truncate(str(title), max(1, inner)) + " "
        bar = g["h"] * max(0, width - 2 - fmt.display_width(label))
        out.append(surface.style(g["tl"] + label + bar + g["tr"], "border"))
    else:
        out.append(surface.style(g["tl"] + g["h"] * (width - 2) + g["tr"], "border"))

    edge = surface.style(g["v"], "border")
    for line in lines:
        text = "" if line is None else str(line)
        out.append(edge + " " + fmt.pad(text, inner) + " " + edge)

    if footer:
        label = " " + fmt.truncate(str(footer), max(1, inner)) + " "
        bar = g["h"] * max(0, width - 2 - fmt.display_width(label))
        out.append(surface.style(g["bl"] + bar + label + g["br"], "border"))
    else:
        out.append(surface.style(g["bl"] + g["h"] * (width - 2) + g["br"], "border"))
    return out


def kv(
    surface: Surface,
    label: Any,
    value: Any,
    width: Optional[int] = None,
    label_width: Optional[int] = None,
    status: bool = False,
) -> str:
    """One aligned ``label  value`` row."""

    width = surface.width if width is None else width
    if label_width is None:
        label_width = min(24, max(10, width // 3))
    rendered_label = fmt.pad(fmt.truncate(str(label), label_width), label_width)
    text = fmt.text_or_placeholder(value)
    if status:
        shown = surface.status(text)
    else:
        shown = surface.style(text, "value")
    room = max(4, width - label_width - 2)
    if fmt.display_width(fmt.strip_ansi(shown)) > room:
        shown = surface.style(fmt.truncate(fmt.strip_ansi(shown), room), "value")
    return surface.style(rendered_label, "label") + "  " + shown


def kv_block(
    surface: Surface,
    rows: Iterable[Tuple[Any, Any]],
    width: Optional[int] = None,
    status_keys: Sequence[str] = (),
) -> List[str]:
    """Render aligned key/value rows, auto sizing the label column."""

    items: List[Tuple[str, Any]] = [(str(k), v) for k, v in rows]
    if not items:
        return []
    width = surface.width if width is None else width
    label_width = min(max(fmt.display_width(k) for k, _ in items), max(10, width // 2))
    return [
        kv(surface, k, v, width=width, label_width=label_width,
           status=(k in status_keys))
        for k, v in items
    ]


def bullet_list(surface: Surface, items: Sequence[Any],
                width: Optional[int] = None) -> List[str]:
    width = surface.width if width is None else width
    marker = surface.glyph("bullet")
    out: List[str] = []
    for item in items:
        wrapped = fmt.wrap(item, max(4, width - 2))
        out.append(surface.style(marker, "muted") + " " + wrapped[0])
        for extra in wrapped[1:]:
            out.append("  " + extra)
    return out


def paragraph(surface: Surface, text: Any, width: Optional[int] = None,
              role: str = "value") -> List[str]:
    width = surface.width if width is None else width
    return [surface.style(line, role) for line in fmt.wrap(text, width)]


def empty_state(surface: Surface, message: str, width: Optional[int] = None) -> List[str]:
    width = surface.width if width is None else width
    return [surface.style(fmt.pad(fmt.truncate(message, width), width, "left"), "muted")]


__all__ = [
    "bullet_list",
    "card",
    "empty_state",
    "kv",
    "kv_block",
    "panel",
    "paragraph",
    "rule",
    "section_title",
]
