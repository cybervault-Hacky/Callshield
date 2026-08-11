"""Phase 8 observe → correlate → score → explain → adapt engine."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from ..database import Database
from ..reputation import ReputationProfile, number_fingerprint
from ..utils import mask_number
from .models import BehaviorObservation, IntelligenceSnapshot
from .patterns import detect_patterns
from .storage import BehaviorStorage
from .trends import NOISE_THRESHOLD, analyze_trend


class BehaviorEngine:
    """Build bounded local context; never applies a phone action directly."""

    def __init__(self, database: Database, cfg: Any) -> None:
        self.database = database
        self.cfg = cfg
        self.storage = BehaviorStorage(database, cfg)

    def snapshot(
        self,
        normalized_number: str,
        *,
        reputation: ReputationProfile,
        detection: Optional[Any] = None,
        observation: Optional[BehaviorObservation] = None,
        persist: bool = True,
    ) -> IntelligenceSnapshot:
        number_hash = number_fingerprint(normalized_number)
        masked = mask_number(normalized_number)
        try:
            if not reputation.available:
                raise RuntimeError("reputation unavailable")
            if observation is not None:
                self.storage.add_observation(
                    number_hash=number_hash,
                    number_masked=masked,
                    event_id=observation.event_id,
                    timestamp=observation.timestamp,
                    event_type=observation.event_type,
                    risk_score=observation.risk_score,
                    confidence=observation.confidence,
                    recommended_action=observation.recommended_action,
                    applied_action=observation.applied_action,
                    confirmed=observation.confirmed,
                    source=observation.source,
                    trust_state=observation.trust_state,
                    trust_expires=observation.trust_expires,
                    evidence=observation.evidence,
                )
            elif persist:
                self.storage.cleanup(number_hash)
            timeline = self.storage.timeline(number_hash)
            previous = self.storage.profile_state(number_hash)
            baseline_score = (
                int(previous["current_score"])
                if previous is not None
                else int(reputation.risk_score)
            )
            baseline_confidence = (
                int(previous["confidence"])
                if previous is not None
                else int(reputation.confidence)
            )
            scores = [item.risk_score for item in timeline]
            confidences = [item.confidence for item in timeline]
            trend = analyze_trend(
                scores,
                confidences,
                baseline_score=baseline_score,
                baseline_confidence=baseline_confidence,
                current_score=reputation.risk_score,
                current_confidence=reputation.confidence,
            )
            now = datetime.now(timezone.utc)
            reports = self.storage.recent_report_count(normalized_number, now)
            trust_expiry = reputation.trusted_until or self.storage.last_trust_expiry(
                timeline
            )
            patterns = detect_patterns(
                timeline,
                reputation=reputation,
                trend=trend,
                recent_reports=reports,
                trusted=reputation.trusted,
                trust_expiry=trust_expiry,
                now=now,
            )
            recent_high = sum(1 for item in timeline if item.risk_score >= 60)
            recent_blocks = sum(
                1 for item in timeline if item.recommended_action == "BLOCK"
            )
            latest = timeline[-1] if timeline else None
            recommended = str(
                _value(detection, "recommended_action", None)
                or (latest.recommended_action if latest else "ALLOW")
            )
            if recommended not in ("ALLOW", "BLOCK"):
                recommended = "ALLOW"
            explanations = [pattern.explanation for pattern in patterns]
            if trend.trend == "WORSENING":
                explanations.append(
                    f"Behavioral risk increased across {len(timeline)} measured observations"
                )
            elif trend.trend == "IMPROVING":
                explanations.append(
                    f"Behavioral risk decreased across {len(timeline)} measured observations"
                )
            elif trend.trend == "VOLATILE":
                explanations.append(
                    f"Behavioral risk changed direction {trend.direction_changes} times"
                )
            elif trend.trend == "STABLE":
                explanations.append(
                    "Behavioral risk remained within configured trend thresholds"
                )
            else:
                explanations.append(
                    f"Only {len(timeline)} observations are available; trend needs at least 3"
                )
            if abs(trend.risk_delta) >= NOISE_THRESHOLD:
                direction = "increased" if trend.risk_delta > 0 else "decreased"
                explanations.append(
                    f"Risk {direction} by {abs(trend.risk_delta)} points from baseline"
                )
            if abs(trend.confidence_delta) >= NOISE_THRESHOLD:
                direction = "increased" if trend.confidence_delta > 0 else "decreased"
                explanations.append(
                    f"Confidence {direction} by {abs(trend.confidence_delta)} points"
                )
            snapshot = IntelligenceSnapshot(
                number_hash=number_hash,
                number_masked=masked,
                reputation_score=int(reputation.risk_score),
                reputation_confidence=int(reputation.confidence),
                behavioral_trend=trend.trend,
                patterns=patterns,
                recent_observation_count=len(timeline),
                recent_high_risk_count=recent_high,
                recent_block_recommendations=recent_blocks,
                recent_user_reports=reports,
                trust_state="TRUSTED" if reputation.trusted else "UNTRUSTED",
                trust_expiry=trust_expiry,
                risk_delta=trend.risk_delta,
                confidence_delta=trend.confidence_delta,
                baseline_score=trend.baseline_score,
                current_score=trend.current_score,
                explanations=_unique(explanations)[:20],
                observed=latest.event_type if latest else "NO_OBSERVATION",
                recommended=recommended,
                applied=(latest.applied_action if latest else "ALLOW"),
                confirmed=(latest.confirmed if latest else False),
                available=True,
                timeline=timeline,
            )
            if persist:
                self.storage.save_snapshot(snapshot)
            return snapshot
        except Exception as exc:
            return IntelligenceSnapshot.unavailable(number_hash, masked, str(exc))

    def add_observation(
        self,
        normalized_number: str,
        observation: BehaviorObservation,
    ) -> bool:
        return self.storage.add_observation(
            number_hash=number_fingerprint(normalized_number),
            number_masked=mask_number(normalized_number),
            event_id=observation.event_id,
            timestamp=observation.timestamp,
            event_type=observation.event_type,
            risk_score=observation.risk_score,
            confidence=observation.confidence,
            recommended_action=observation.recommended_action,
            applied_action=observation.applied_action,
            confirmed=observation.confirmed,
            source=observation.source,
            trust_state=observation.trust_state,
            trust_expires=observation.trust_expires,
            evidence=observation.evidence,
        )

    def update_outcome(
        self, event_id: str, *, recommended_action: str, applied_action: str
    ) -> bool:
        return self.storage.update_outcome(
            event_id,
            recommended_action=recommended_action,
            applied_action=applied_action,
        )

    def confirm(self, event_id: str) -> bool:
        return self.storage.confirm(event_id)


def _value(value: Any, key: str, default: Any) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default) if value is not None else default


def _unique(values: list) -> list:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
