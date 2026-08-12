"""Presentation primitives: colour palette, glyph tables, terminal probing."""

from .capabilities import (
    MIN_WIDTH,
    NARROW_WIDTH,
    WIDE_WIDTH,
    Capabilities,
    detect,
    detect_size,
    detect_unicode,
    is_interactive,
)
from .glyphs import Glyphs
from .palette import APPEARANCES, RESET, STATUS_ROLE, Theme, resolve_appearance

__all__ = [
    "APPEARANCES",
    "Capabilities",
    "Glyphs",
    "MIN_WIDTH",
    "NARROW_WIDTH",
    "RESET",
    "STATUS_ROLE",
    "Theme",
    "WIDE_WIDTH",
    "detect",
    "detect_size",
    "detect_unicode",
    "is_interactive",
    "resolve_appearance",
]
