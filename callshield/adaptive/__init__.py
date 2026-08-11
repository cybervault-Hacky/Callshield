"""Phase 8 local adaptive threat intelligence."""

from .engine import BehaviorEngine
from .models import (
    ADAPTIVE_TRENDS,
    BehaviorObservation,
    BehaviorPattern,
    IntelligenceSnapshot,
    TrendResult,
)
from .storage import BehaviorStorage, BehaviorStorageError
from .trends import (
    NOISE_THRESHOLD,
    SUDDEN_CHANGE_THRESHOLD,
    SUSTAINED_DELTA,
    VOLATILITY_RANGE,
    analyze_trend,
)

__all__ = [
    "BehaviorEngine",
    "BehaviorStorage",
    "BehaviorStorageError",
    "BehaviorObservation",
    "BehaviorPattern",
    "IntelligenceSnapshot",
    "TrendResult",
    "ADAPTIVE_TRENDS",
    "NOISE_THRESHOLD",
    "SUSTAINED_DELTA",
    "SUDDEN_CHANGE_THRESHOLD",
    "VOLATILITY_RANGE",
    "analyze_trend",
]
