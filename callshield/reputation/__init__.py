"""CALLSHIELD reputation APIs through Phase 7.

Legacy Phase 1 imports remain available alongside the new profile engine.
"""

from .engine import ReputationEngine
from .legacy import (
    REPUTATION_LEVELS as LEGACY_REPUTATION_LEVELS,
    SUSPICIOUS_VERDICTS,
    ReputationSignals,
    classify_reputation,
    gather_signals,
)
from .models import (
    RISK_LEVELS,
    TRENDS,
    ReputationHistoryEntry,
    ReputationProfile,
    ReputationSignal,
    TrustedRecord,
)
from .storage import (
    ReputationStorage,
    ReputationStorageError,
    number_fingerprint,
    trust_expiry,
)

# Preserve the historical name used by Phase 1 callers.
REPUTATION_LEVELS = LEGACY_REPUTATION_LEVELS

__all__ = [
    "ReputationEngine",
    "ReputationStorage",
    "ReputationStorageError",
    "ReputationProfile",
    "ReputationSignal",
    "ReputationHistoryEntry",
    "TrustedRecord",
    "RISK_LEVELS",
    "TRENDS",
    "ReputationSignals",
    "REPUTATION_LEVELS",
    "SUSPICIOUS_VERDICTS",
    "gather_signals",
    "classify_reputation",
    "number_fingerprint",
    "trust_expiry",
]
