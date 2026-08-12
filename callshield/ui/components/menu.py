"""Selectable menu list.

The menu carries no behaviour beyond selection bookkeeping; the owning screen
decides what an item does. Every item is reachable both by arrow keys and by a
number shortcut, so the user is never trapped in a mode.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from .. import formatters as fmt
from .base import Surface


class MenuItem:
    def __init__(
        self,
        key: str,
        label: str,
        hint: str = "",
        enabled: bool = True,
        status: str = "",
    ) -> None:
        self.key = str(key)
        self.label = str(label)
        self.hint = str(hint)
        self.enabled = bool(enabled)
        self.status = str(status)


class Menu:
    """Selection state over a list of :class:`MenuItem`."""

    def __init__(self, items: Optional[Sequence[MenuItem]] = None,
                 index: int = 0) -> None:
        self.items: List[MenuItem] = list(items or [])
        self.index = 0
        if self.items:
            self.index = max(0, min(int(index), len(self.items) - 1))
            if not self.items[self.index].enabled:
                self.move(1)

    # ----------------------------------------------------------- navigation
    def __len__(self) -> int:
        return len(self.items)

    @property
    def selected(self) -> Optional[MenuItem]:
        if not self.items:
            return None
        return self.items[self.index]

    def move(self, delta: int) -> Optional[MenuItem]:
        """Move the cursor, skipping disabled entries, wrapping at the ends."""

        if not self.items:
            return None
        step = 1 if delta >= 0 else -1
        position = self.index
        for _ in range(len(self.items)):
            position = (position + step) % len(self.items)
            if self.items[position].enabled:
                self.index = position
                break
        return self.selected

    def first(self) -> Optional[MenuItem]:
        for position, item in enumerate(self.items):
            if item.enabled:
                self.index = position
                break
        return self.selected

    def last(self) -> Optional[MenuItem]:
        for position in range(len(self.items) - 1, -1, -1):
            if self.items[position].enabled:
                self.index = position
                break
        return self.selected

    def select_index(self, position: int) -> Optional[MenuItem]:
        if 0 <= position < len(self.items) and self.items[position].enabled:
            self.index = position
            return self.items[position]
        return None

    def select_number(self, number: int) -> Optional[MenuItem]:
        """Number shortcuts are 1-based and match the printed order."""

        return self.select_index(number - 1)

    def by_key(self, key: str) -> Optional[MenuItem]:
        for item in self.items:
            if item.key == key:
                return item
        return None

    def replace(self, items: Sequence[MenuItem]) -> None:
        """Swap the item list, keeping the cursor position when possible."""

        previous = self.selected.key if self.selected else None
        self.items = list(items)
        self.index = 0
        if previous:
            for position, item in enumerate(self.items):
                if item.key == previous:
                    self.index = position
                    break
        if self.items and not self.items[self.index].enabled:
            self.move(1)


def render_menu(surface: Surface, menu: Menu, width: Optional[int] = None,
                numbered: bool = False) -> List[str]:
    """Draw the menu.

    Selection is a single cursor glyph plus an accent-coloured label — never a
    full line of inverse video. ``numbered`` is retained for callers that want
    a hint of the 1-9 shortcuts, but the default is the quiet, unnumbered look.
    """

    width = surface.width if width is None else width
    out: List[str] = []
    cursor = surface.glyph("cursor")
    cursor_width = fmt.display_width(cursor)

    for position, item in enumerate(menu.items):
        marker = cursor if position == menu.index else " " * cursor_width
        number = "{0}.".format(position + 1) if numbered and position < 9 else ""
        label = item.label
        prefix = "{0} {1} ".format(marker, number).rstrip() if number else marker
        body = "{0} {1}".format(prefix, label).rstrip()
        room = width - fmt.display_width(body)

        trailing = item.status or item.hint
        if trailing and room > fmt.display_width(trailing) + 2:
            gap = room - fmt.display_width(trailing)
            if item.status:
                body = body + " " * gap + surface.status(item.status)
            else:
                body = body + " " * gap + surface.style(trailing, "muted")

        if not item.enabled:
            out.append(surface.style(fmt.truncate(fmt.strip_ansi(body), width),
                                     "muted"))
        elif position == menu.index:
            # The marker and the label take the accent colour; foreground-only
            # styling means padding stays invisible, so the row reads as a
            # clean highlight rather than a block of inverse video.
            plain = fmt.strip_ansi(body)
            rest = fmt.truncate(plain[cursor_width:], max(1, width - cursor_width))
            out.append(surface.style(marker, "selected")
                       + surface.style(rest, "selected"))
        else:
            out.append(body)
    return out


__all__ = ["Menu", "MenuItem", "render_menu"]
