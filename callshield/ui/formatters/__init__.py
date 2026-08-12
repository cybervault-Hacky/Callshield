"""Value formatting helpers.

Presentation only: these functions never compute risk, reputation or policy
outcomes, they only shape values the backend already produced. Anything the
backend did not provide renders as an explicit placeholder rather than an
invented value.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, List, Optional, Sequence

from ...utils import mask_number

PLACEHOLDER = "--"

# Facts CALLSHIELD cannot know. Listed here so reviewers can see the intent:
# the UI never renders call duration, caller identity, location, audio
# analysis, contact details, answered-call state, carrier or any external
# reputation feed. There is deliberately no formatter for any of them.
UNKNOWABLE_FIELDS = (
    "call_duration",
    "caller_name",
    "caller_identity",
    "location",
    "audio_analysis",
    "contact_info",
    "answered",
    "carrier",
    "external_reputation",
)


_ANSI_RE = re.compile(r"\033\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: Any) -> str:
    """Remove SGR/CSI escape sequences so widths can be measured."""

    return _ANSI_RE.sub("", "" if text is None else str(text))


def display_width(text: str) -> int:
    """Column width of ``text``: ANSI-aware and wide-character aware."""

    width = 0
    for char in strip_ansi(text):
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def truncate(text: Any, limit: int, ellipsis: str = "...") -> str:
    """Cut ``text`` to ``limit`` display columns."""

    value = "" if text is None else str(text)
    if limit <= 0:
        return ""
    if display_width(value) <= limit:
        return value
    # Styled text cannot be cut safely mid-escape; drop the styling instead.
    value = strip_ansi(value)
    if display_width(value) <= limit:
        return value
    if limit <= display_width(ellipsis):
        out: List[str] = []
        used = 0
        for char in value:
            step = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
            if used + step > limit:
                break
            out.append(char)
            used += step
        return "".join(out)
    budget = limit - display_width(ellipsis)
    out = []
    used = 0
    for char in value:
        step = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if used + step > budget:
            break
        out.append(char)
        used += step
    return "".join(out) + ellipsis


def pad(text: Any, width: int, align: str = "left") -> str:
    """Pad ``text`` to ``width`` display columns."""

    value = "" if text is None else str(text)
    value = truncate(value, width)
    gap = max(0, width - display_width(value))
    if align == "right":
        return " " * gap + value
    if align == "center":
        left = gap // 2
        return " " * left + value + " " * (gap - left)
    return value + " " * gap


def masked(number: Any) -> str:
    """Mask a phone number for display. Raw numbers never reach the screen."""

    if not number:
        return PLACEHOLDER
    try:
        return mask_number(str(number))
    except Exception:  # noqa: BLE001 - display must not fail
        return PLACEHOLDER


def text_or_placeholder(value: Any, placeholder: str = PLACEHOLDER) -> str:
    if value is None:
        return placeholder
    value = str(value).strip()
    return value if value else placeholder


def integer(value: Any, placeholder: str = PLACEHOLDER) -> str:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return placeholder


def score(value: Any, placeholder: str = PLACEHOLDER) -> str:
    """Render a 0-100 score without inventing precision."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return placeholder
    if number != number:  # NaN
        return placeholder
    if abs(number - round(number)) < 0.05:
        return str(int(round(number)))
    return "{0:.1f}".format(number)


def percent(value: Any, placeholder: str = PLACEHOLDER) -> str:
    rendered = score(value, placeholder)
    return rendered if rendered == placeholder else rendered + "%"


def signed(value: Any, placeholder: str = PLACEHOLDER) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return placeholder
    rendered = score(number)
    if rendered == placeholder:
        return placeholder
    return ("+" + rendered) if number > 0 else rendered


def duration(seconds: Any, placeholder: str = PLACEHOLDER) -> str:
    """Human-readable process duration (never a call duration)."""

    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return placeholder
    if total < 0:
        return placeholder
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return "{0}d {1}h {2}m".format(days, hours, minutes)
    if hours:
        return "{0}h {1}m".format(hours, minutes)
    if minutes:
        return "{0}m {1}s".format(minutes, secs)
    return "{0}s".format(secs)


def timestamp(value: Any, placeholder: str = PLACEHOLDER, short: bool = False) -> str:
    """Render an ISO-8601 timestamp as stored, optionally shortened."""

    if not value:
        return placeholder
    text = str(value).strip()
    if not text:
        return placeholder
    text = text.replace("T", " ")
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        text = text.split(".", 1)[0]
    if short and len(text) > 16:
        text = text[5:16]
    return text


def bytes_kb(value: Any, placeholder: str = PLACEHOLDER) -> str:
    try:
        kb = float(value)
    except (TypeError, ValueError):
        return placeholder
    if kb < 1024:
        return "{0:.0f} KB".format(kb)
    return "{0:.1f} MB".format(kb / 1024.0)


def yes_no(value: Any, yes: str = "YES", no: str = "NO") -> str:
    return yes if value else no


def status_word(value: Any, placeholder: str = "UNKNOWN") -> str:
    """Normalise a backend state into a canonical uppercase status word."""

    if value is None:
        return placeholder
    text = str(value).strip()
    if not text:
        return placeholder
    if text in ("--", "-"):
        # The unknown-value placeholder is not a state; never mangle it.
        return text
    return text.upper().replace("-", "_")


def bar(value: Any, width: int = 20, full: str = "#", empty: str = ".") -> str:
    """Proportional bar for a 0-100 value; empty string when unknown."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    number = max(0.0, min(100.0, number))
    if width <= 0:
        return ""
    filled = int(round((number / 100.0) * width))
    return full * filled + empty * (width - filled)


def wrap(text: Any, width: int) -> List[str]:
    """Word-wrap ``text`` to ``width`` display columns."""

    value = "" if text is None else str(text)
    if width <= 0:
        return [value]
    lines: List[str] = []
    for paragraph in value.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = word if not current else current + " " + word
            if display_width(candidate) <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                while display_width(word) > width:
                    lines.append(truncate(word, width, ""))
                    word = word[len(truncate(word, width, "")):]
                current = word
        if current:
            lines.append(current)
    return lines or [""]


def join_list(values: Optional[Iterable[Any]], separator: str = ", ",
              placeholder: str = PLACEHOLDER) -> str:
    if not values:
        return placeholder
    items = [str(item).strip() for item in values if str(item).strip()]
    if not items:
        return placeholder
    return separator.join(items)


def columns(rows: Sequence[Sequence[Any]]) -> List[int]:
    """Compute the display width of each column across ``rows``."""

    widths: List[int] = []
    for row in rows:
        for index, cell in enumerate(row):
            cell_width = display_width("" if cell is None else str(cell))
            if index >= len(widths):
                widths.append(cell_width)
            elif cell_width > widths[index]:
                widths[index] = cell_width
    return widths


__all__ = [
    "PLACEHOLDER",
    "UNKNOWABLE_FIELDS",
    "bar",
    "bytes_kb",
    "columns",
    "display_width",
    "strip_ansi",
    "duration",
    "integer",
    "join_list",
    "masked",
    "pad",
    "percent",
    "score",
    "signed",
    "status_word",
    "text_or_placeholder",
    "timestamp",
    "truncate",
    "wrap",
    "yes_no",
]
