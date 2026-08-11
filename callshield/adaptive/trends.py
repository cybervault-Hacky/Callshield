"""Deterministic bounded Phase 8 trend and delta analysis."""

from __future__ import annotations

from typing import Iterable, List

from .models import TrendResult


NOISE_THRESHOLD = 5
SUSTAINED_DELTA = 10
SUDDEN_CHANGE_THRESHOLD = 20
VOLATILITY_RANGE = 25


def analyze_trend(
    scores: Iterable[int],
    confidences: Iterable[int],
    *,
    baseline_score: int,
    baseline_confidence: int,
    current_score: int,
    current_confidence: int,
) -> TrendResult:
    bounded_scores = [max(0, min(100, int(value))) for value in scores][-20:]
    bounded_confidences = [
        max(0, min(100, int(value))) for value in confidences
    ][-20:]
    current = max(0, min(100, int(current_score)))
    current_conf = max(0, min(100, int(current_confidence)))
    baseline = max(0, min(100, int(baseline_score)))
    baseline_conf = max(0, min(100, int(baseline_confidence)))
    risk_delta = current - baseline
    confidence_delta = current_conf - baseline_conf

    values = list(bounded_scores)
    if not values or values[-1] != current:
        values.append(current)
    values = values[-20:]
    if len(values) < 3:
        return TrendResult(
            "INSUFFICIENT_DATA",
            baseline,
            current,
            risk_delta,
            confidence_delta,
            abs(risk_delta) >= SUDDEN_CHANGE_THRESHOLD,
            0,
        )

    meaningful_steps = [
        values[index] - values[index - 1]
        for index in range(1, len(values))
        if abs(values[index] - values[index - 1]) >= NOISE_THRESHOLD
    ]
    direction_changes = _direction_changes(meaningful_steps)
    observed_range = max(values) - min(values)
    sudden_change = any(
        abs(values[index] - values[index - 1]) >= SUDDEN_CHANGE_THRESHOLD
        for index in range(1, len(values))
    )

    if observed_range >= VOLATILITY_RANGE and direction_changes >= 2:
        trend = "VOLATILE"
    else:
        increases = sum(1 for value in meaningful_steps if value > 0)
        decreases = sum(1 for value in meaningful_steps if value < 0)
        required = max(2, (len(meaningful_steps) + 1) // 2)
        total_delta = values[-1] - values[0]
        if total_delta >= SUSTAINED_DELTA and increases >= required:
            trend = "WORSENING"
        elif total_delta <= -SUSTAINED_DELTA and decreases >= required:
            trend = "IMPROVING"
        else:
            trend = "STABLE"

    return TrendResult(
        trend,
        baseline,
        current,
        risk_delta,
        confidence_delta,
        sudden_change,
        direction_changes,
    )


def _direction_changes(steps: List[int]) -> int:
    directions = [1 if value > 0 else -1 for value in steps if value]
    return sum(
        1 for index in range(1, len(directions))
        if directions[index] != directions[index - 1]
    )
