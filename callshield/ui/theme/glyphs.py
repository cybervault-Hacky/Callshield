"""Box-drawing and marker glyphs with an ASCII fallback set.

Terminals that cannot render UTF-8 (some minimal Termux setups, `TERM=dumb`,
piped output) get the ASCII table instead. No emoji is defined anywhere.
"""

from __future__ import annotations

from typing import Dict

UNICODE: Dict[str, str] = {
    "h": "─",
    "v": "│",
    "tl": "┌",
    "tr": "┐",
    "bl": "└",
    "br": "┘",
    "lt": "├",
    "rt": "┤",
    "heavy": "═",
    "bullet": "·",
    "arrow": "›",
    "cursor": "▸",
    "bar_full": "█",
    "bar_empty": "░",
    "ellipsis": "…",
}

ASCII: Dict[str, str] = {
    "h": "-",
    "v": "|",
    "tl": "+",
    "tr": "+",
    "bl": "+",
    "br": "+",
    "lt": "+",
    "rt": "+",
    "heavy": "=",
    "bullet": "*",
    "arrow": ">",
    "cursor": ">",
    "bar_full": "#",
    "bar_empty": ".",
    "ellipsis": "...",
}

# Spinner frames are deliberately plain so they render everywhere.
SPINNER_UNICODE = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
SPINNER_ASCII = ("|", "/", "-", "\\")


class Glyphs:
    """Glyph table bound to a terminal's Unicode capability."""

    def __init__(self, unicode_ok: bool = True) -> None:
        self.unicode = bool(unicode_ok)
        self._table = UNICODE if self.unicode else ASCII
        self.spinner = SPINNER_UNICODE if self.unicode else SPINNER_ASCII

    def __getitem__(self, key: str) -> str:
        return self._table.get(key, "")

    def get(self, key: str, default: str = "") -> str:
        return self._table.get(key, default)

    def spinner_frame(self, tick: int) -> str:
        if not self.spinner:
            return ""
        return self.spinner[tick % len(self.spinner)]


__all__ = ["ASCII", "Glyphs", "SPINNER_ASCII", "SPINNER_UNICODE", "UNICODE"]
