"""Shared utility helpers for CALLSHIELD."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_USAGE = 2
EXIT_INVALID_NUMBER = 3
EXIT_DATABASE = 4
EXIT_CONFIG = 5
EXIT_DAEMON = 6


class CallShieldError(Exception):
    """Base exception for expected, user-facing CALLSHIELD errors."""

    exit_code: int = EXIT_GENERAL

    def __init__(self, message: str, exit_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        if exit_code is not None:
            self.exit_code = exit_code


class ConfigError(CallShieldError):
    exit_code = EXIT_CONFIG


class DatabaseError(CallShieldError):
    exit_code = EXIT_DATABASE


class InvalidNumberError(CallShieldError):
    exit_code = EXIT_INVALID_NUMBER


def utcnow() -> datetime:
    """Return an aware UTC datetime. Used everywhere for consistent timestamps."""
    return datetime.now(timezone.utc)


def iso_now() -> str:
    """ISO-8601 UTC timestamp string."""
    return utcnow().isoformat(timespec="seconds")


def mask_number(number: str) -> str:
    """Mask a phone number for safe display in logs.

    Keeps the country-code prefix and last four digits, redacting the middle
    with asterisks. Short numbers are partially masked rather than fully shown.
    """
    if not number:
        return "****"
    digits = "".join(ch for ch in number if ch.isdigit())
    if len(digits) <= 4:
        return "*" * len(digits)
    # Preserve leading '+' if present
    leading_plus = "+" if number.startswith("+") else ""
    keep_prefix = min(3, max(0, len(digits) - 4 - 2))
    prefix = digits[:keep_prefix]
    middle = "*" * max(2, len(digits) - keep_prefix - 4)
    suffix = digits[-4:]
    return f"{leading_plus}{prefix}{middle}{suffix}"


def ensure_parent(path: Path) -> Path:
    """Create parent directories for ``path`` if necessary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def safe_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Write ``content`` to ``path`` atomically-ish with restricted permissions.

    Permissions are set so that other users on the same host cannot read the
    file (important for local databases/logs containing phone numbers).
    """
    ensure_parent(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    try:
        os.chmod(tmp, mode)
    except OSError:
        # chmod may fail on exotic filesystems; continue rather than break.
        pass
    os.replace(tmp, path)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def supports_color(no_color: bool = False) -> bool:
    """Best-effort detection of ANSI color support.

    Honors:
      * explicit ``--no-color`` flag
      * ``NO_COLOR`` environment variable (https://no-color.org/)
      * TTY check on stdout
    """
    if no_color:
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("CLICOLOR_FORCE", "0") != "0":
        return True
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
