from datetime import datetime, timedelta, timezone

from callshield.adaptive import BehaviorObservation
from callshield.reputation import ReputationProfile, number_fingerprint
from callshield.utils import mask_number


def observation(
    index,
    risk,
    confidence=70,
    recommended="ALLOW",
    applied="ALLOW",
    event_type="NUMBER_SCAN",
    timestamp=None,
    trust_state="UNTRUSTED",
    trust_expires=None,
):
    when = timestamp or (
        datetime.now(timezone.utc) + timedelta(seconds=index)
    ).isoformat(timespec="seconds")
    return BehaviorObservation(
        event_id=f"00000000-0000-4000-8000-{index:012d}",
        timestamp=when,
        event_type=event_type,
        risk_score=risk,
        confidence=confidence,
        recommended_action=recommended,
        applied_action=applied,
        confirmed=False,
        source="TEST",
        trust_state=trust_state,
        trust_expires=trust_expires,
        evidence={"index": index},
    )


def reputation(number, score=50, confidence=60, trusted=False, reports=0, allowed=0, blocks=0):
    return ReputationProfile(
        number_hash=number_fingerprint(number),
        number_masked=mask_number(number),
        risk_score=0 if trusted else score,
        confidence=100 if trusted else confidence,
        risk="TRUSTED" if trusted else "MODERATE",
        trend="UNKNOWN",
        trusted=trusted,
        user_reports=reports,
        calls_allowed=allowed,
        block_recommendations=blocks,
        available=True,
    )
