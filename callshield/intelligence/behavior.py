"""Historical behavior analysis and local number intelligence.

Purely local: scans the event/report/number tables to derive structured
statistics about past observations of a number.

Number-intelligence heuristics are WEAK signals only. They must never by
themselves cause a BLOCK verdict, and they are tuned to be very
conservative so ordinary real-world numbers (e.g. +919876543210) do not
trigger false positives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..database import Database


# ----- Number intelligence -----------------------------------------------
NUMBER_INTELLIGENCE_DEFAULTS: Dict[str, Any] = {
    "format": "VALID",
    "pattern_risk": "LOW",
    "anomalies": [],
}

# 8+ identical digits in a row, e.g. 999999999.
_REPEATED_DIGITS_RE = re.compile(r"(\d)\1{7,}")

# Characters that are NOT expected in raw phone input. We only flag if
# such characters survive; the normalizer already rejects many bad inputs.
_INVALID_CHARS_RE = re.compile(r"[^\d\s\-\+\(\)\.\[\]/]")


@dataclass
class NumberIntelligence:
    format: str = "VALID"                     # VALID | ANOMALOUS
    pattern_risk: str = "LOW"                 # LOW | MEDIUM
    anomalies: List[str] = field(default_factory=list)
    length: int = 0
    normalized: str = ""
    original: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": self.format,
            "pattern_risk": self.pattern_risk,
            "anomalies": list(self.anomalies),
            "length": self.length,
            "normalized": self.normalized,
        }


def number_intelligence(raw: str, normalized: str, digits: str) -> NumberIntelligence:
    """Analyze a number's formatting for weak pattern-based signals."""
    intel = NumberIntelligence(
        normalized=normalized,
        original=raw,
        length=len(digits),
    )
    anomalies: List[str] = []

    if _INVALID_CHARS_RE.search(raw):
        anomalies.append("unexpected characters present")

    # Extremely long runs of repeated digits — classic vanity/spam pattern.
    if _REPEATED_DIGITS_RE.search(digits):
        anomalies.append("long run of repeated digits")

    # All digits identical (after stripping a leading 0 trunk prefix).
    core = digits.lstrip("0") or digits
    if len(core) >= 8 and len(set(core)) == 1:
        anomalies.append("all digits identical")

    # Unusual length (outside the ITU-T E.164 7-15 range). Normalizer already
    # clamped to 7-15, so this only fires on outliers inside that range when
    # combined with other signals; we keep it very conservative.
    if len(digits) < 8:
        anomalies.append("unusually short digit length")
    if len(digits) > 14:
        anomalies.append("unusually long digit length")

    if anomalies:
        intel.format = "ANOMALOUS"
        intel.pattern_risk = "MEDIUM" if len(anomalies) >= 2 else "LOW"
        intel.anomalies = anomalies
    return intel


# ----- Behavioral history ------------------------------------------------
@dataclass
class BehaviorAnalysis:
    total_events: int = 0
    suspicious_events: int = 0
    blocked_events: int = 0
    allowed_events: int = 0
    safe_events: int = 0
    unknown_events: int = 0
    user_reports: int = 0
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    recent_window_count: int = 0
    window_seconds: int = 600
    activity_level: str = "NONE"  # NONE | LOW | MODERATE | HIGH

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_events": self.total_events,
            "suspicious_events": self.suspicious_events,
            "blocked_events": self.blocked_events,
            "allowed_events": self.allowed_events,
            "safe_events": self.safe_events,
            "unknown_events": self.unknown_events,
            "user_reports": self.user_reports,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "recent_window_count": self.recent_window_count,
            "window_seconds": self.window_seconds,
            "activity_level": self.activity_level,
        }


def get_number_history(db: Database, number: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Return a chronologically-ordered list of events for ``number``."""
    events = db.get_events_for_number(number, limit=limit)
    return list(reversed(events))  # oldest first


def analyze_behavior(
    db: Database,
    number: str,
    *,
    window_seconds: int = 600,
) -> BehaviorAnalysis:
    """Compute behavioral statistics for ``number`` using local history."""
    b = BehaviorAnalysis(window_seconds=window_seconds)

    events = db.get_events_for_number(number, limit=10000)
    b.total_events = len(events)

    b.blocked_events = sum(1 for e in events if e["action"] == "BLOCK")
    b.allowed_events = sum(1 for e in events if e["action"] == "ALLOW")
    b.safe_events = sum(1 for e in events if e["verdict"] == "SAFE")
    b.unknown_events = sum(1 for e in events if e["verdict"] == "UNKNOWN")
    b.suspicious_events = sum(
        1 for e in events
        if e["verdict"] in ("SUSPICIOUS", "HIGH_RISK", "MALICIOUS", "MEDIUM_RISK")
    )
    b.user_reports = db.count_reports(number)
    b.first_seen = db.get_first_seen(number)
    b.last_seen = db.get_last_seen(number)
    b.recent_window_count = db.recent_event_window_count(number, window_seconds)

    if b.total_events == 0 and b.user_reports == 0:
        b.activity_level = "NONE"
    elif b.recent_window_count >= 3 or b.total_events >= 6 or b.user_reports >= 2:
        b.activity_level = "HIGH"
    elif b.total_events >= 2 or b.user_reports >= 1:
        b.activity_level = "MODERATE"
    else:
        b.activity_level = "LOW"
    return b
