"""Shared drawing surface for the component library.

A :class:`Surface` bundles the terminal capabilities, the colour theme and the
glyph table so components stay pure functions of (surface, data) -> lines.
Components never touch the database, the daemon or the network.
"""

from __future__ import annotations

from typing import Any, List, Optional

from .. import formatters as fmt
from ..theme import Capabilities, Glyphs, Theme


class Surface:
    """Immutable-ish drawing context handed to every component."""

    def __init__(
        self,
        caps: Optional[Capabilities] = None,
        theme: Optional[Theme] = None,
        glyphs: Optional[Glyphs] = None,
    ) -> None:
        self.caps = caps if caps is not None else Capabilities()
        self.theme = theme if theme is not None else Theme("DARK", self.caps.color)
        self.glyphs = glyphs if glyphs is not None else Glyphs(self.caps.unicode)

    # ------------------------------------------------------------- geometry
    @property
    def width(self) -> int:
        return max(fmt.display_width("") + 20, min(self.caps.width, 120))

    @property
    def inner(self) -> int:
        """Usable width inside a panel border."""

        return max(8, self.width - 4)

    @property
    def narrow(self) -> bool:
        return self.caps.narrow

    # -------------------------------------------------------------- styling
    def style(self, text: Any, role: str) -> str:
        return self.theme.style("" if text is None else str(text), role)

    def status(self, word: Any) -> str:
        return self.theme.status(fmt.status_word(word))

    def glyph(self, name: str) -> str:
        return self.glyphs[name]

    def resized(self, caps: Capabilities) -> "Surface":
        return Surface(caps, self.theme.with_color(caps.color), Glyphs(caps.unicode))

    def with_theme(self, theme: Theme) -> "Surface":
        return Surface(self.caps, theme, self.glyphs)


def blank(count: int = 1) -> List[str]:
    return [""] * max(0, count)


__all__ = ["Surface", "blank"]
