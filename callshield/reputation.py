"""Local reputation engine.

Phase 1 uses purely local signals. The reputation is computed from:

  * explicit blacklist/whitelist membership
  * user-supplied reason text
  * stored reputation field on the numbers table
  * count of previous suspicious events for the number

Unknown numbers remain UNKNOWN — we never label them as fraudulent without
positive signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .database import Database


REPUTATION_LEVELS = ("UNKNOWN", "LOW", "MEDIUM", "HIGH", "CRITICAL")
SUSPICIOUS_VERDICTS = ("HIGH_RISK", "MEDIUM_RISK")


@dataclass
class ReputationSignals:
    in_blacklist: bool = False
    in_whitelist: bool = False
    stored_reputation: str = "UNKNOWN"
    previous_suspicious: int = 0
    reason: Optional[str] = None
    conflict: bool = False  # True when present in BOTH lists


def gather_signals(db: Database, number: str) -> ReputationSignals:
    """Collect reputation signals for ``number`` from the local database."""
    sig = ReputationSignals()
    blacklist_row = None
    whitelist_row = None
    for row in db.list_numbers():
        if row["number"] == number:
            if row["list_type"] == "blacklist":
                blacklist_row = row
            else:
                whitelist_row = row
    sig.in_blacklist = blacklist_row is not None
    sig.in_whitelist = whitelist_row is not None
    sig.conflict = sig.in_blacklist and sig.in_whitelist
    # Choose stored reputation by precedence when both present.
    if sig.in_whitelist:
        sig.stored_reputation = whitelist_row["reputation"]
        sig.reason = whitelist_row.get("reason") or sig.reason
    elif sig.in_blacklist:
        sig.stored_reputation = blacklist_row["reputation"]
        sig.reason = blacklist_row.get("reason") or sig.reason
    sig.previous_suspicious = db.count_events_for_number(
        number, verdict_match=SUSPICIOUS_VERDICTS
    )
    return sig


def classify_reputation(score: int) -> str:
    """Map a numeric score to a reputation tier label."""
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    if score > 0:
        return "LOW"
    return "UNKNOWN"
