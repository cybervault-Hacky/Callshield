"""Raw keyboard decoding.

Uses only ``termios``/``tty``/``select`` from the standard library, all of which
are available under Termux. Reads are non-blocking with a timeout so the main
loop can refresh data while waiting, and the terminal state is always restored
even if the screen raises.
"""

from __future__ import annotations

import os
import select
import sys
from typing import Any, List, Optional

try:  # pragma: no cover - POSIX only, but Termux/Linux always have these
    import termios
    import tty
except ImportError:  # pragma: no cover - non-POSIX fallback
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]

# Canonical key names used by the whole UI.
UP = "UP"
DOWN = "DOWN"
LEFT = "LEFT"
RIGHT = "RIGHT"
ENTER = "ENTER"
ESC = "ESC"
TAB = "TAB"
BACKSPACE = "BACKSPACE"
HOME = "HOME"
END = "END"
PAGE_UP = "PGUP"
PAGE_DOWN = "PGDN"
INTERRUPT = "CTRL_C"
RESIZE = "RESIZE"
NONE = ""

NAVIGATION_KEYS = (UP, DOWN, LEFT, RIGHT, ENTER, ESC, PAGE_UP, PAGE_DOWN, HOME, END)

_CSI_FINAL = {
    "A": UP,
    "B": DOWN,
    "C": RIGHT,
    "D": LEFT,
    "H": HOME,
    "F": END,
}

_CSI_TILDE = {
    "1": HOME,
    "3": "DELETE",
    "4": END,
    "5": PAGE_UP,
    "6": PAGE_DOWN,
    "7": HOME,
    "8": END,
}


def decode(sequence: str) -> str:
    """Translate a raw escape sequence into a canonical key name.

    Unknown sequences resolve to ``ESC`` rather than being swallowed, so the
    user can always back out of a screen.
    """

    if not sequence:
        return NONE
    if sequence in ("\r", "\n"):
        return ENTER
    if sequence == "\t":
        return TAB
    if sequence in ("\x7f", "\b"):
        return BACKSPACE
    if sequence == "\x03":
        return INTERRUPT
    if sequence == "\x1b":
        return ESC
    if sequence.startswith("\x1b"):
        body = sequence[1:]
        if body.startswith("[") or body.startswith("O"):
            body = body[1:]
        if not body:
            return ESC
        if body[-1] == "~":
            return _CSI_TILDE.get(body[:-1].split(";")[0], ESC)
        final = body[-1]
        return _CSI_FINAL.get(final, ESC)
    if len(sequence) == 1:
        return sequence
    return sequence[0]


def is_quit(key: str) -> bool:
    return key in ("q", "Q", INTERRUPT)


def is_back(key: str) -> bool:
    return key in (ESC, BACKSPACE, "b", "B")


def is_digit(key: str) -> bool:
    return len(key) == 1 and key.isdigit()


class KeyReader:
    """Reads single keys from a TTY, restoring terminal state on exit."""

    def __init__(self, stream: Any = None) -> None:
        self.stream = stream if stream is not None else sys.stdin
        self._saved = None
        self._fd = None
        try:
            self._fd = self.stream.fileno()
        except Exception:  # noqa: BLE001 - StringIO and friends
            self._fd = None

    # ------------------------------------------------------------- lifecycle
    @property
    def usable(self) -> bool:
        if termios is None or tty is None or self._fd is None:
            return False
        try:
            return bool(self.stream.isatty())
        except Exception:  # noqa: BLE001
            return False

    def __enter__(self) -> "KeyReader":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def open(self) -> None:
        if not self.usable or self._saved is not None:
            return
        try:
            self._saved = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        except Exception:  # noqa: BLE001 - terminal refused raw mode
            self._saved = None

    def close(self) -> None:
        if self._saved is None or self._fd is None:
            return
        try:
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
        except Exception:  # noqa: BLE001
            pass
        finally:
            self._saved = None

    # ------------------------------------------------------------- reading
    def _wait(self, timeout: Optional[float]) -> bool:
        if self._fd is None:
            return False
        try:
            ready, _, _ = select.select([self._fd], [], [], timeout)
        except (OSError, ValueError):
            return False
        except InterruptedError:  # pragma: no cover - signal during select
            return False
        return bool(ready)

    def _read_byte(self) -> str:
        try:
            data = os.read(self._fd, 1)
        except (OSError, ValueError):
            return ""
        if not data:
            return ""
        try:
            return data.decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return ""

    def read_key(self, timeout: Optional[float] = None) -> str:
        """Return one canonical key name, or ``""`` when the timeout expires."""

        if not self.usable:
            return NONE
        if not self._wait(timeout):
            return NONE
        first = self._read_byte()
        if not first:
            return NONE
        if first != "\x1b":
            return decode(first)

        # Escape sequence: collect the remainder without blocking.
        chars: List[str] = ["\x1b"]
        if not self._wait(0.05):
            return ESC
        chars.append(self._read_byte())
        if chars[-1] in ("[", "O"):
            for _ in range(8):
                if not self._wait(0.02):
                    break
                char = self._read_byte()
                if not char:
                    break
                chars.append(char)
                if char.isalpha() or char == "~":
                    break
        return decode("".join(chars))


def read_line(prompt: str = "", stream: Any = None) -> Optional[str]:
    """Blocking line input used by prompts. ``None`` means the user aborted."""

    stream = stream if stream is not None else sys.stdin
    try:
        sys.stdout.write(prompt)
        sys.stdout.flush()
        line = stream.readline()
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception:  # noqa: BLE001 - closed stream
        return None
    if line == "":
        return None
    return line.rstrip("\r\n")


__all__ = [
    "BACKSPACE",
    "DOWN",
    "END",
    "ENTER",
    "ESC",
    "HOME",
    "INTERRUPT",
    "KeyReader",
    "LEFT",
    "NAVIGATION_KEYS",
    "NONE",
    "PAGE_DOWN",
    "PAGE_UP",
    "RESIZE",
    "RIGHT",
    "TAB",
    "UP",
    "decode",
    "is_back",
    "is_digit",
    "is_quit",
    "read_line",
]
