"""Phone-number normalization.

CALLSHIELD does not bundle libphonenumber or make risky guesses about country
codes. Phase 1 uses a conservative, deterministic normalizer that:

  * strips whitespace and common punctuation
  * preserves a single leading '+'
  * accepts an optional configured default country code (applied only when the
    input looks like a local number, i.e. starts with '0' or has no country
    prefix and matches the configured length)
  * rejects obviously malformed input

The canonical stored form is E.164-ish: a leading '+' followed by digits only,
e.g. ``+919876543210``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .utils import InvalidNumberError

# Characters we strip before further processing (spaces, separators, common
# formatting symbols).
_STRIP_CHARS_RE = re.compile(r"[\s\-\.\(\)\[\]/\\]+")

# Allowed characters after stripping: leading optional '+', then digits.
_VALID_RE = re.compile(r"^\+?\d+$")

# Minimum/maximum plausible digit counts (excluding any leading '+').
MIN_DIGITS = 7
MAX_DIGITS = 15


@dataclass(frozen=True)
class NormalizationResult:
    """Result of a successful normalization."""

    original: str
    normalized: str  # canonical form: '+<digits>'
    digits: str      # digits only, no '+'
    country_code: Optional[str]  # detected/applied country code, if known


def normalize(
    value: str,
    default_country: Optional[str] = None,
) -> NormalizationResult:
    """Normalize ``value`` into a canonical form.

    Raises :class:`InvalidNumberError` if the input is unsafe to accept.
    """
    if value is None:
        raise InvalidNumberError("No phone number provided.")
    if not isinstance(value, str):
        raise InvalidNumberError("Phone number must be a string.")

    cleaned = _STRIP_CHARS_RE.sub("", value.strip())
    if not cleaned:
        raise InvalidNumberError("Phone number is empty.")

    # Drop a leading '00' international dialing prefix, convert to '+'.
    if cleaned.startswith("00") and not cleaned.startswith("+"):
        cleaned = "+" + cleaned[2:]

    # Collapse a stray leading double '+'.
    while cleaned.startswith("++"):
        cleaned = cleaned[1:]

    if not _VALID_RE.match(cleaned):
        raise InvalidNumberError(
            "Invalid phone number: contains unexpected characters. "
            "Use digits, optional leading '+', spaces, dashes or parentheses."
        )

    had_plus = cleaned.startswith("+")
    digits = cleaned.lstrip("+")

    # Leading '0' with no '+' is a classic trunk/long-distance prefix. If a
    # default country is configured we drop the trunk '0' and prepend the
    # configured code. Otherwise we leave it but will still validate length.
    applied_cc: Optional[str] = None
    if not had_plus and default_country:
        cc = _country_code_for(default_country)
        if cc:
            if digits.startswith("0") and len(digits) > 1:
                digits_local = digits.lstrip("0")
                candidate = cc + digits_local
                if MIN_DIGITS <= len(candidate) <= MAX_DIGITS:
                    digits = candidate
                    applied_cc = cc
            else:
                # No trunk prefix; if length looks local for the country, prepend.
                candidate = cc + digits
                if MIN_DIGITS <= len(candidate) <= MAX_DIGITS and len(digits) < MIN_DIGITS:
                    digits = candidate
                    applied_cc = cc

    if not (MIN_DIGITS <= len(digits) <= MAX_DIGITS):
        raise InvalidNumberError(
            f"Invalid phone number: expected {MIN_DIGITS}-{MAX_DIGITS} digits, "
            f"got {len(digits)}."
        )

    # If the number already had a '+', the leading digits are a country code.
    if had_plus and applied_cc is None:
        # Best-effort: do NOT guess the country; just note we can't identify it
        # without a lookup table. We keep the digits as-is in canonical form.
        applied_cc = None

    normalized = "+" + digits
    return NormalizationResult(
        original=value,
        normalized=normalized,
        digits=digits,
        country_code=applied_cc,
    )


def _country_code_for(country: str) -> Optional[str]:
    """Map a configured default country to its ITU E.164 country calling code.

    This mapping is intentionally small and conservative. Only widely-known
    codes are included; unknown countries cause us to skip automatic prefixing
    rather than guessing.
    """
    if not country:
        return None
    c = country.strip().upper()
    table = {
        "US": "1", "CA": "1",
        "GB": "44", "UK": "44",
        "IN": "91",
        "DE": "49", "FR": "33", "ES": "34", "IT": "39",
        "AU": "61", "NZ": "64",
        "JP": "81", "KR": "82", "CN": "86",
        "BR": "55", "MX": "52", "RU": "7",
        "NL": "31", "BE": "32", "SE": "46", "NO": "47", "DK": "45", "FI": "358",
        "PT": "351", "CH": "41", "AT": "43",
        "ZA": "27", "NG": "234", "EG": "20",
    }
    return table.get(c)
