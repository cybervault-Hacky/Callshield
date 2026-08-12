"""Dense, alignment-aware tables that collapse gracefully on narrow terminals."""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from .. import formatters as fmt
from .base import Surface


class Column:
    """A table column description."""

    def __init__(
        self,
        title: str,
        width: int = 0,
        align: str = "left",
        min_width: int = 3,
        priority: int = 1,
        status: bool = False,
    ) -> None:
        self.title = str(title)
        self.width = int(width)
        self.align = align
        self.min_width = max(1, int(min_width))
        self.priority = int(priority)  # lower is dropped first when cramped
        self.status = bool(status)


def _natural_widths(columns: Sequence[Column],
                    rows: Sequence[Sequence[Any]]) -> List[int]:
    widths = []
    for index, column in enumerate(columns):
        if column.width:
            widths.append(column.width)
            continue
        best = fmt.display_width(column.title)
        for row in rows:
            if index < len(row):
                best = max(best, fmt.display_width(fmt.strip_ansi(row[index])))
        widths.append(max(column.min_width, best))
    return widths


def fit_columns(columns: Sequence[Column], rows: Sequence[Sequence[Any]],
                width: int) -> List[int]:
    """Choose which columns survive and how wide each becomes."""

    keep = list(range(len(columns)))
    while True:
        widths = _natural_widths([columns[i] for i in keep], rows)
        total = sum(widths) + 2 * (len(keep) - 1)
        if total <= width or len(keep) <= 1:
            break
        # Drop the lowest-priority column (last one at that priority).
        lowest = min(columns[i].priority for i in keep)
        for i in reversed(keep):
            if columns[i].priority == lowest:
                keep.remove(i)
                break

    widths = _natural_widths([columns[i] for i in keep], rows)
    total = sum(widths) + 2 * (len(keep) - 1)
    if total > width:
        # Shrink the widest remaining column(s) until it fits.
        overflow = total - width
        order = sorted(range(len(keep)), key=lambda i: widths[i], reverse=True)
        for i in order:
            if overflow <= 0:
                break
            slack = widths[i] - columns[keep[i]].min_width
            take = min(slack, overflow)
            widths[i] -= take
            overflow -= take
    result = [0] * len(columns)
    for position, index in enumerate(keep):
        result[index] = widths[position]
    return result


def table(
    surface: Surface,
    columns: Sequence[Column],
    rows: Sequence[Sequence[Any]],
    width: Optional[int] = None,
    empty_message: str = "No records.",
    show_header: bool = True,
) -> List[str]:
    """Render ``rows`` as a table, hiding columns that no longer fit."""

    width = surface.width if width is None else width
    if not rows:
        return [surface.style(fmt.truncate(empty_message, width), "muted")]

    widths = fit_columns(columns, rows, width)
    visible = [i for i, w in enumerate(widths) if w > 0]
    out: List[str] = []

    if show_header:
        header = "  ".join(
            fmt.pad(columns[i].title, widths[i], columns[i].align) for i in visible
        )
        out.append(surface.style(header, "label"))
        out.append(surface.style(surface.glyph("h") * min(width,
                   fmt.display_width(header)), "border"))

    for row in rows:
        cells = []
        for i in visible:
            raw = row[i] if i < len(row) else ""
            text = fmt.truncate(fmt.strip_ansi(raw), widths[i])
            padded = fmt.pad(text, widths[i], columns[i].align)
            if columns[i].status:
                padded = surface.theme.status(text) + " " * max(
                    0, widths[i] - fmt.display_width(text)
                ) if columns[i].align == "left" else padded
            cells.append(padded)
        out.append("  ".join(cells))
    return out


__all__ = ["Column", "fit_columns", "table"]
