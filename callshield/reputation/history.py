"""Bounded historical trend calculation for local reputation."""

from __future__ import annotations

from typing import Iterable, List, Optional


TRENDS = ("IMPROVING", "STABLE", "WORSENING", "UNKNOWN")


def detect_trend(previous_scores: Iterable[int], current_score: int) -> str:
    """Require at least three observations and a meaningful ten-point change."""

    values = [max(0, min(100, int(value))) for value in previous_scores]
    values.append(max(0, min(100, int(current_score))))
    if len(values) < 3:
        return "UNKNOWN"
    # Bound trend work even if a caller passes a larger iterable.
    values = values[-10:]
    midpoint = max(1, len(values) // 2)
    early = values[:midpoint]
    late = values[-midpoint:]
    early_average = sum(early) / len(early)
    late_average = sum(late) / len(late)
    delta = late_average - early_average
    if delta >= 10:
        return "WORSENING"
    if delta <= -10:
        return "IMPROVING"
    return "STABLE"


def meaningful_change(
    old_score: Optional[int],
    new_score: int,
    old_risk: Optional[str],
    new_risk: str,
) -> bool:
    if old_score is None:
        return True
    return abs(int(new_score) - int(old_score)) >= 5 or old_risk != new_risk


def history_trigger(signal_names: List[str], trend: str) -> str:
    measured = [name for name in signal_names if name][:3]
    if trend in ("IMPROVING", "WORSENING"):
        measured.append(f"trend_{trend.lower()}")
    return ",".join(measured)[:200] or "observation"
