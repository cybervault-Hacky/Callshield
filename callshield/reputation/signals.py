"""Deterministic reputation signals derived from measured local history."""

from __future__ import annotations

from typing import Any, Dict, List

from .models import ReputationSignal


def build_reputation_signals(
    measurements: Dict[str, Any],
    *,
    current_risk: int,
    current_confidence: int,
    trusted: bool,
) -> List[ReputationSignal]:
    signals = []  # type: List[ReputationSignal]
    if trusted:
        signals.append(
            ReputationSignal(
                name="explicit_local_trust",
                score_delta=-100,
                confidence=100,
                measurement=1,
                reason="Explicit local trust is active",
            )
        )
        return signals

    reports = int(measurements.get("user_reports", 0))
    if reports:
        signals.append(
            ReputationSignal(
                name="user_reports",
                score_delta=min(24, reports * 8),
                confidence=min(95, 45 + reports * 10),
                measurement=reports,
                reason=f"{reports} local user report{'s' if reports != 1 else ''}",
            )
        )

    recent_calls = int(measurements.get("recent_calls_24h", 0))
    if recent_calls >= 3:
        signals.append(
            ReputationSignal(
                name="recent_call_frequency",
                score_delta=min(18, (recent_calls - 2) * 3),
                confidence=min(90, 40 + recent_calls * 5),
                measurement=recent_calls,
                reason=f"{recent_calls} calls observed within 24 hours",
            )
        )

    block_recommendations = int(measurements.get("block_recommendations", 0))
    if block_recommendations:
        signals.append(
            ReputationSignal(
                name="historical_block_recommendations",
                score_delta=min(30, block_recommendations * 6),
                confidence=min(95, 50 + block_recommendations * 7),
                measurement=block_recommendations,
                reason=(
                    f"{block_recommendations} historical BLOCK recommendation"
                    f"{'s' if block_recommendations != 1 else ''}"
                ),
            )
        )

    high_risk = int(measurements.get("high_risk_detections", 0))
    if high_risk:
        signals.append(
            ReputationSignal(
                name="recent_high_risk_detections",
                score_delta=min(24, high_risk * 6),
                confidence=min(95, 45 + high_risk * 8),
                measurement=high_risk,
                reason=f"{high_risk} measured high-risk detection{'s' if high_risk != 1 else ''}",
            )
        )

    allowed = int(measurements.get("calls_allowed", 0))
    seen = int(measurements.get("calls_seen", 0))
    if seen >= 3 and allowed >= 3 and block_recommendations == 0 and high_risk == 0:
        signals.append(
            ReputationSignal(
                name="historical_allows",
                score_delta=-min(15, allowed * 2),
                confidence=min(90, 45 + allowed * 5),
                measurement=allowed,
                reason=f"{allowed} historical allowed interactions without a BLOCK recommendation",
            )
        )

    # Reuse the existing detector measurement as context rather than creating
    # a second detector. A zero score produces no synthetic reason.
    if current_risk > 0:
        signals.append(
            ReputationSignal(
                name="current_local_analysis",
                score_delta=0,
                confidence=max(0, min(100, current_confidence)),
                measurement=max(0, min(100, current_risk)),
                reason=f"Current local analysis measured risk {current_risk}/100",
            )
        )
    return signals
