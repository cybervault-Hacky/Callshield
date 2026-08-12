"""Colour palette and status vocabulary for the CALLSHIELD interface.

Design rules enforced here:

* Colour is decoration only. Every state also has a *word* (ONLINE, OFFLINE,
  WARNING, ERROR, NOT VERIFIED, DRY RUN, ACTIVE, DISABLED, ...), so the UI stays
  readable on monochrome terminals, in pipes and for colour-blind users.
* No emoji, no neon "hacker" styling — a calm instrument-panel look.
"""

from __future__ import annotations

from typing import Dict

RESET = "\033[0m"

# Semantic roles -> SGR sequences, per appearance.
#
# The palette is intentionally restrained — an instrument panel rather than a
# neon dashboard. Colours are muted, selection never uses full-line inverse
# video, and every state keeps its word so monochrome terminals stay readable.
_DARK: Dict[str, str] = {
    "title": "\033[1;97m",
    "brand": "\033[1;97m",
    "label": "\033[38;5;246m",
    "value": "\033[97m",
    "muted": "\033[2;37m",
    "border": "\033[38;5;238m",
    "accent": "\033[38;5;45m",
    "ok": "\033[38;5;114m",
    "warn": "\033[38;5;215m",
    "err": "\033[38;5;203m",
    "info": "\033[38;5;111m",
    "selected": "\033[1;38;5;45m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}

_LIGHT: Dict[str, str] = {
    "title": "\033[1;30m",
    "brand": "\033[1;30m",
    "label": "\033[38;5;240m",
    "value": "\033[30m",
    "muted": "\033[2;30m",
    "border": "\033[38;5;250m",
    "accent": "\033[34m",
    "ok": "\033[32m",
    "warn": "\033[33m",
    "err": "\033[31m",
    "info": "\033[34m",
    "selected": "\033[1;34m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}

APPEARANCES = ("DARK", "LIGHT", "SYSTEM")

# Canonical status words. Colour never carries meaning on its own.
STATUS_ROLE: Dict[str, str] = {
    "ONLINE": "ok",
    "READY": "ok",
    "RUNNING": "ok",
    "ENABLED": "ok",
    "HEALTHY": "ok",
    "OK": "ok",
    "ALLOW": "ok",
    "ALLOWED": "ok",
    "LOW": "ok",
    "TRUSTED": "ok",
    "IMPROVING": "ok",
    "PASS": "ok",
    "OFFLINE": "warn",
    "STOPPED": "muted",
    "STANDBY": "muted",
    "DISABLED": "muted",
    "UNKNOWN": "muted",
    "NOT VERIFIED": "muted",
    "INSUFFICIENT_DATA": "muted",
    "UNTRUSTED": "muted",
    "MANUAL": "muted",
    "DRY RUN": "warn",
    "DRY_RUN": "warn",
    "WARNING": "warn",
    "STALE": "warn",
    "MODERATE": "warn",
    "MEDIUM": "warn",
    "MONITOR": "warn",
    "VOLATILE": "warn",
    "WORSENING": "warn",
    "EXPIRED": "warn",
    "ACTIVE": "err",
    "ERROR": "err",
    "CRITICAL": "err",
    "HIGH": "err",
    "BLOCK": "err",
    "BLOCKED": "err",
    "BLOCK_RECOMMENDED": "err",
    "FAIL": "err",
    "STABLE": "info",
}


class Theme:
    """Resolves semantic roles into terminal escape sequences."""

    def __init__(self, appearance: str = "DARK", color: bool = True) -> None:
        self.appearance = (appearance or "DARK").upper()
        if self.appearance not in APPEARANCES:
            self.appearance = "DARK"
        self.color = bool(color)
        self._table = _LIGHT if self.appearance == "LIGHT" else _DARK

    # ------------------------------------------------------------- styling
    def code(self, role: str) -> str:
        if not self.color:
            return ""
        return self._table.get(role, "")

    def style(self, text: str, role: str) -> str:
        """Wrap ``text`` in the escape sequence for ``role``."""

        if not self.color:
            return text
        code = self._table.get(role, "")
        if not code:
            return text
        return f"{code}{text}{RESET}"

    def status(self, word: str) -> str:
        """Style a canonical status word (word itself is never changed)."""

        if not word:
            return ""
        text = str(word).strip()
        if text in ("--", "-"):
            # The unknown-value placeholder must survive verbatim; canonical
            # status casing would otherwise turn "--" into "__".
            return self.style(text, "muted")
        role = STATUS_ROLE.get(text.upper(), "value")
        return self.style(text, role)

    def risk(self, level: str) -> str:
        return self.status(level)

    # ------------------------------------------------------------- helpers
    def with_appearance(self, appearance: str) -> "Theme":
        return Theme(appearance, self.color)

    def with_color(self, color: bool) -> "Theme":
        return Theme(self.appearance, color)


def resolve_appearance(preference: str, *, system_default: str = "DARK") -> str:
    """Map a user preference (DARK/LIGHT/SYSTEM) onto a concrete appearance."""

    value = (preference or "DARK").upper()
    if value == "SYSTEM":
        return (system_default or "DARK").upper()
    if value not in APPEARANCES:
        return "DARK"
    return value


__all__ = ["APPEARANCES", "RESET", "STATUS_ROLE", "Theme", "resolve_appearance"]
