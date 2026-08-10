"""Confidence scoring.

Risk score and confidence are *not* the same thing. A number may be risky but
with little evidence (high risk, low confidence), or clearly safe with strong
evidence (low risk, high confidence).

Confidence is computed from:
  * the weight (``confidence`` field) of each triggered signal
  * the count of independent signals that agreed
  * presence of conflicting signals (whitelist + blacklist)
  * depth of local history (more events = higher confidence, capped)

Confidence is an integer 0-100 and is fully deterministic.
"""

from __future__ import annotations

from typing import List, Sequence

from .signals import SignalResult


def compute_confidence(signals: Sequence[SignalResult], history_depth: int = 0) -> int:
    """Return a confidence score 0..100."""
    if not signals:
        # No signals at all -> unknown, low/moderate confidence that there's
        # nothing we know about it.
        return 25

    # Separate polarity.
    positive = [s for s in signals if s.positive and s.score > 0]
    negative = [s for s in signals if (not s.positive) or s.score < 0]
    info_only = [s for s in signals if s.score == 0]

    has_conflict = any(s.name == "list_conflict" for s in signals)
    strong_pos = [s for s in positive if s.confidence >= 0.8]
    strong_neg = [s for s in negative if s.confidence >= 0.8]

    # Base confidence from average weighted signal confidence.
    weighted = 0.0
    total_weight = 0.0
    for s in positive + negative:
        w = abs(s.score) * max(s.confidence, 0.05)
        weighted += s.confidence * w
        total_weight += w
    base = (weighted / total_weight) if total_weight > 0 else 0.0

    # Agreement bonus: more independent signals agreeing -> more confidence.
    agreement_bonus = min(15, 5 * max(len(positive), len(negative)))

    # History bonus: more past observations -> more confidence.
    history_bonus = min(10, history_depth)  # +1 per event capped at 10.

    # Conflict penalty.
    conflict_penalty = 20 if has_conflict else 0

    # Strong-signal dominance — one very strong signal (e.g. blacklist) still
    # gives high confidence on its own.
    strength_bonus = 0
    if strong_pos and not strong_neg:
        strength_bonus = 10 + 5 * min(len(strong_pos), 2)
    if strong_neg and not strong_pos:
        strength_bonus = 15

    value = base * 65 + agreement_bonus + history_bonus + strength_bonus - conflict_penalty

    # Clamp
    value = max(5, min(99, int(round(value))))
    return int(value)
