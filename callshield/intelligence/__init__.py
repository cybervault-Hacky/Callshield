"""Phase 2 intelligence layer: signals, behavior, confidence, profiles, reputation."""

from .behavior import (
    BehaviorAnalysis,
    NumberIntelligence,
    NUMBER_INTELLIGENCE_DEFAULTS,
    analyze_behavior,
    get_number_history,
    number_intelligence,
)
from .confidence import compute_confidence
from .profiles import PROFILES, Profile, get_profile
from .reputation import (
    REPUTATION_LEVELS,
    ReputationResult,
    classify_reputation,
    reputation_from_score,
)
from .signals import SignalResult, SignalContext, evaluate_signals

__all__ = [
    "SignalResult",
    "SignalContext",
    "evaluate_signals",
    "BehaviorAnalysis",
    "NumberIntelligence",
    "NUMBER_INTELLIGENCE_DEFAULTS",
    "analyze_behavior",
    "get_number_history",
    "number_intelligence",
    "compute_confidence",
    "PROFILES",
    "Profile",
    "get_profile",
    "REPUTATION_LEVELS",
    "ReputationResult",
    "classify_reputation",
    "reputation_from_score",
]
