"""Deterministic, explainable, local-first Phase 7 reputation engine."""

from __future__ import annotations

from statistics import mean
from typing import Any, Dict, List, Mapping, Optional

from ..database import Database
from ..utils import mask_number
from .history import detect_trend, history_trigger
from .models import ReputationProfile, ReputationSignal
from .signals import build_reputation_signals
from .storage import ReputationStorage, number_fingerprint


class ReputationEngine:
    def __init__(self, database: Database, cfg: Any) -> None:
        self.database = database
        self.cfg = cfg
        self.storage = ReputationStorage(database, cfg)

    def calculate(
        self,
        normalized_number: str,
        *,
        analysis: Optional[Any] = None,
        persist: bool = True,
    ) -> ReputationProfile:
        number_hash = number_fingerprint(normalized_number)
        masked = mask_number(normalized_number)
        try:
            trust = self.storage.get_trust(number_hash)
            now_iso = _now_iso()
            measured = self.storage.measurements(normalized_number, now_iso)
            current_risk = _value(analysis, "risk_score", 0)
            current_confidence = _value(analysis, "confidence", 0)
            existing_signals = _analysis_signals(analysis)
            if not current_risk and measured["recent_scores"]:
                current_risk = int(measured["recent_scores"][0])
            if not current_confidence and measured["recent_confidences"]:
                current_confidence = int(measured["recent_confidences"][0])

            signals = build_reputation_signals(
                measured,
                current_risk=current_risk,
                current_confidence=current_confidence,
                trusted=trust is not None,
            )
            signals.extend(existing_signals)
            score = _score_reputation(measured, current_risk, signals, trust is not None)
            evidence_count = (
                int(measured["calls_seen"])
                + int(measured["user_reports"])
                + len(existing_signals)
            )
            confidence = _confidence(
                measured,
                current_confidence=current_confidence,
                signal_count=len(signals),
                trusted=trust is not None,
            )
            previous = self.storage.history(number_hash, limit=9)
            previous_scores = [entry.new_score for entry in reversed(previous)]
            trend = detect_trend(previous_scores, score)
            risk = _risk_level(score, evidence_count, trust is not None)
            reasons = _unique_reasons(signals)
            if trend == "WORSENING":
                reasons.append("Measured reputation risk increased across recent observations")
            elif trend == "IMPROVING":
                reasons.append("Measured reputation risk decreased across recent observations")

            profile = ReputationProfile(
                number_hash=number_hash,
                number_masked=masked,
                first_seen=measured.get("first_seen"),
                last_seen=measured.get("last_seen"),
                calls_seen=int(measured["calls_seen"]),
                calls_answered=int(measured["calls_answered"]),
                calls_rejected=int(measured["calls_rejected"]),
                calls_allowed=int(measured["calls_allowed"]),
                block_recommendations=int(measured["block_recommendations"]),
                user_reports=int(measured["user_reports"]),
                risk_score=score,
                confidence=confidence,
                risk=risk,
                trend=trend,
                trusted=trust is not None,
                trusted_until=trust.expires_at if trust else None,
                signals=signals[:20],
                reasons=reasons[:20],
                recommendation="ALLOW",  # Reputation alone never forces BLOCK.
                available=True,
            )
            trigger = history_trigger([signal.name for signal in signals], trend)
            if persist:
                self.storage.save_profile(profile, trigger)
                profile.history = self.storage.history(number_hash, limit=20)
            else:
                profile.history = previous[:20]
            return profile
        except Exception as exc:
            return ReputationProfile.unavailable(number_hash, masked, str(exc))


def _score_reputation(
    measured: Dict[str, Any],
    current_risk: int,
    signals: List[ReputationSignal],
    trusted: bool,
) -> int:
    if trusted:
        return 0
    recent_scores = [int(value) for value in measured.get("recent_scores", [])[:20]]
    if current_risk and recent_scores:
        base = round(current_risk * 0.6 + mean(recent_scores) * 0.4)
    elif current_risk:
        base = current_risk
    elif recent_scores:
        base = round(mean(recent_scores))
    else:
        base = 0
    delta = sum(signal.score_delta for signal in signals)
    return max(0, min(100, int(round(base + delta))))


def _confidence(
    measured: Dict[str, Any],
    *,
    current_confidence: int,
    signal_count: int,
    trusted: bool,
) -> int:
    if trusted:
        return 100
    calls = int(measured.get("calls_seen", 0))
    reports = int(measured.get("user_reports", 0))
    blocks = int(measured.get("block_recommendations", 0))
    value = (
        min(45, calls * 6)
        + min(20, reports * 5)
        + min(15, blocks * 3)
        + min(15, max(0, current_confidence) // 6)
        + min(5, signal_count)
    )
    return max(0, min(100, value))


def _risk_level(score: int, evidence_count: int, trusted: bool) -> str:
    if trusted:
        return "TRUSTED"
    if evidence_count <= 0:
        return "UNKNOWN"
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MODERATE"
    return "LOW"


def _analysis_signals(analysis: Any) -> List[ReputationSignal]:
    values = _raw_value(analysis, "signals", [])
    if not isinstance(values, list):
        return []
    results = []  # type: List[ReputationSignal]
    for item in values[:10]:
        if not isinstance(item, Mapping):
            continue
        score = item.get("score", 0)
        reason = item.get("reason")
        name = item.get("name")
        confidence = item.get("confidence", 0)
        if not isinstance(name, str) or not isinstance(reason, str):
            continue
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        if score <= 0:
            continue
        results.append(
            ReputationSignal(
                name=f"detector_{name}"[:64],
                score_delta=0,
                confidence=max(0, min(100, int(confidence or 0))),
                measurement=max(0, min(100, int(score))),
                reason=reason[:200],
            )
        )
    return results


def _unique_reasons(signals: List[ReputationSignal]) -> List[str]:
    reasons = []  # type: List[str]
    for signal in signals:
        if signal.reason and signal.reason not in reasons:
            reasons.append(signal.reason)
    return reasons


def _raw_value(value: Any, key: str, default: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default) if value is not None else default


def _value(value: Any, key: str, default: int) -> int:
    raw = _raw_value(value, key, default)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return default
    return max(0, min(100, int(raw)))


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
