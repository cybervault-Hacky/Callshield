"""Explainable patterns based only on measured CALLSHIELD history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .models import BehaviorObservation, BehaviorPattern, TrendResult


PATTERN_WINDOW_SECONDS = 7 * 24 * 60 * 60


def detect_patterns(
    observations: List[BehaviorObservation],
    *,
    reputation: Any,
    trend: TrendResult,
    recent_reports: int,
    trusted: bool,
    trust_expiry: Optional[str],
    now: Optional[datetime] = None,
) -> List[BehaviorPattern]:
    current_time = now or datetime.now(timezone.utc)
    recent = [
        item for item in observations
        if _age_seconds(item.timestamp, current_time) <= PATTERN_WINDOW_SECONDS
    ]
    high_risk = [item for item in recent if item.risk_score >= 60]
    block_recommended = [
        item for item in recent if item.recommended_action == "BLOCK"
    ]
    patterns = []  # type: List[BehaviorPattern]

    if len(high_risk) >= 3:
        patterns.append(
            _pattern(
                "repeated_high_risk",
                {"high_risk_observations": len(high_risk), "threshold": 60},
                len(high_risk),
                min(95, 55 + len(high_risk) * 6),
                f"{len(high_risk)} risk observations at or above 60 in 7 days",
            )
        )
    if len(block_recommended) >= 3:
        patterns.append(
            _pattern(
                "repeated_block_recommendation",
                {"block_recommendations": len(block_recommended)},
                len(block_recommended),
                min(95, 60 + len(block_recommended) * 5),
                f"{len(block_recommended)} BLOCK recommendations in 7 days",
            )
        )
    elif block_recommended:
        patterns.append(
            _pattern(
                "previously_block_recommended",
                {"block_recommendations": len(block_recommended)},
                len(block_recommended),
                min(80, 40 + len(block_recommended) * 10),
                f"A previous BLOCK recommendation was measured in 7 days",
            )
        )
    if recent_reports >= 2:
        patterns.append(
            _pattern(
                "repeated_user_reports",
                {"user_reports": recent_reports},
                recent_reports,
                min(95, 55 + recent_reports * 8),
                f"{recent_reports} local user reports in the retention window",
            )
        )
    if trend.trend == "WORSENING" and trend.risk_delta >= 15:
        patterns.append(
            _pattern(
                "rapidly_increasing_risk",
                {"risk_delta": trend.risk_delta, "baseline": trend.baseline_score},
                len(observations),
                min(95, 60 + min(30, trend.risk_delta)),
                f"Risk increased by {trend.risk_delta} points from baseline",
            )
        )
    if trend.trend == "IMPROVING" and trend.risk_delta <= -15:
        patterns.append(
            _pattern(
                "recently_improved",
                {"risk_delta": trend.risk_delta, "baseline": trend.baseline_score},
                len(observations),
                min(90, 60 + min(25, abs(trend.risk_delta))),
                f"Risk decreased by {abs(trend.risk_delta)} points from baseline",
            )
        )
    if trend.trend == "VOLATILE":
        patterns.append(
            _pattern(
                "inconsistent_behavior",
                {
                    "direction_changes": trend.direction_changes,
                    "risk_delta": trend.risk_delta,
                },
                len(observations),
                min(90, 55 + trend.direction_changes * 10),
                f"Risk direction changed {trend.direction_changes} times",
            )
        )
    calls_allowed = int(getattr(reputation, "calls_allowed", 0))
    blocks = int(getattr(reputation, "block_recommendations", 0))
    if trusted or (calls_allowed >= 3 and blocks == 0):
        patterns.append(
            _pattern(
                "historically_trusted",
                {"trusted": trusted, "allowed_interactions": calls_allowed},
                max(1, calls_allowed),
                100 if trusted else min(90, 50 + calls_allowed * 7),
                (
                    "Explicit local trust is active"
                    if trusted
                    else f"{calls_allowed} allowed interactions without BLOCK recommendations"
                ),
            )
        )
    if not trusted and _expired(trust_expiry, current_time):
        patterns.append(
            _pattern(
                "trust_expired",
                {"trust_expiry": trust_expiry},
                1,
                100,
                "A measured temporary trust record expired",
            )
        )
    return patterns[:20]


def _pattern(
    pattern_id: str,
    evidence: Dict[str, Any],
    count: int,
    confidence: int,
    explanation: str,
) -> BehaviorPattern:
    return BehaviorPattern(
        pattern_id=pattern_id,
        evidence=evidence,
        observation_count=max(0, int(count)),
        time_window_seconds=PATTERN_WINDOW_SECONDS,
        confidence=max(0, min(100, int(confidence))),
        explanation=explanation,
    )


def _age_seconds(timestamp: str, now: datetime) -> float:
    try:
        value = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if value.tzinfo is None:
            return float("inf")
        return max(0.0, (now - value.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return float("inf")


def _expired(value: Optional[str], now: datetime) -> bool:
    if not value:
        return False
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return expiry.tzinfo is not None and expiry.astimezone(timezone.utc) <= now
    except (TypeError, ValueError):
        return False
