"""Terminal capability detection for the CALLSHIELD interface.

The UI must degrade gracefully: no colour, limited Unicode, very narrow or very
wide terminals, and fully non-interactive pipes. Everything here is read-only
probing of the environment — no side effects, no network, no subprocesses.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Optional

from ...utils import supports_color

# Layout breakpoints (terminal columns).
MIN_WIDTH = 40
NARROW_WIDTH = 64
WIDE_WIDTH = 100

DEFAULT_SIZE = (80, 24)


@dataclass
class Capabilities:
    """Immutable snapshot of what the attached terminal can do."""

    width: int = DEFAULT_SIZE[0]
    height: int = DEFAULT_SIZE[1]
    color: bool = False
    unicode: bool = False
    interactive: bool = False

    @property
    def narrow(self) -> bool:
        return self.width < NARROW_WIDTH

    @property
    def cramped(self) -> bool:
        """Terminal is too small for the standard layout."""
        return self.width < MIN_WIDTH or self.height < 10

    @property
    def wide(self) -> bool:
        return self.width >= WIDE_WIDTH

    @property
    def body_height(self) -> int:
        """Rows available for screen content (header + footer reserved)."""
        return max(4, self.height - 6)

    def replace(self, **changes: Any) -> "Capabilities":
        data = {
            "width": self.width,
            "height": self.height,
            "color": self.color,
            "unicode": self.unicode,
            "interactive": self.interactive,
        }
        data.update(changes)
        return Capabilities(**data)


def _stream_isatty(stream: Any) -> bool:
    try:
        return bool(stream.isatty())
    except Exception:  # noqa: BLE001 - defensive: exotic stream objects
        return False


def detect_unicode(stream: Any = None) -> bool:
    """True when the output encoding can carry box-drawing characters."""

    if os.environ.get("CALLSHIELD_UI_ASCII"):
        return False
    stream = stream if stream is not None else sys.stdout
    encoding = getattr(stream, "encoding", None) or ""
    if not encoding:
        encoding = os.environ.get("PYTHONIOENCODING", "")
    encoding = encoding.lower()
    if "utf" in encoding:
        return True
    for name in ("LC_ALL", "LC_CTYPE", "LANG"):
        value = (os.environ.get(name) or "").lower()
        if "utf" in value:
            return True
    return False


def detect_size(stream: Any = None) -> tuple:
    """Return (columns, rows), falling back to a sane default."""

    try:
        size = shutil.get_terminal_size(fallback=DEFAULT_SIZE)
        columns, rows = int(size.columns), int(size.lines)
    except Exception:  # noqa: BLE001 - defensive
        columns, rows = DEFAULT_SIZE
    if columns <= 0:
        columns = DEFAULT_SIZE[0]
    if rows <= 0:
        rows = DEFAULT_SIZE[1]
    # Guard against absurd values reported by some terminal emulators.
    columns = max(20, min(columns, 400))
    rows = max(6, min(rows, 200))
    return columns, rows


def detect(
    stdin: Optional[Any] = None,
    stdout: Optional[Any] = None,
    *,
    color_mode: str = "AUTO",
) -> Capabilities:
    """Probe the terminal attached to ``stdin``/``stdout``."""

    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    columns, rows = detect_size(stdout)
    interactive = _stream_isatty(stdin) and _stream_isatty(stdout)

    mode = (color_mode or "AUTO").upper()
    if mode == "ON":
        color = True
    elif mode == "OFF":
        color = False
    else:
        color = bool(supports_color(no_color=False)) and interactive

    return Capabilities(
        width=columns,
        height=rows,
        color=color,
        unicode=detect_unicode(stdout),
        interactive=interactive,
    )


def is_interactive(stdin: Optional[Any] = None, stdout: Optional[Any] = None) -> bool:
    """True when a full-screen interface can safely be drawn."""

    if os.environ.get("CALLSHIELD_NO_UI"):
        return False
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    if not (_stream_isatty(stdin) and _stream_isatty(stdout)):
        return False
    term = (os.environ.get("TERM") or "").strip().lower()
    if term in ("dumb", "unknown"):
        return False
    return True


__all__ = [
    "Capabilities",
    "MIN_WIDTH",
    "NARROW_WIDTH",
    "WIDE_WIDTH",
    "detect",
    "detect_size",
    "detect_unicode",
    "is_interactive",
]
