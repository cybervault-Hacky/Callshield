"""Protection profiles.

Profiles (called "modes" in Phase 1) adjust thresholds and signal weights so
behavior shifts toward fewer false positives (RELAXED), normal protection
(BALANCED), or stronger blocking recommendations when evidence is strong
(STRICT). They must never invent new capabilities — they only tune parameters
that are evaluated by the rule engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict


@dataclass(frozen=True)
class Profile:
    name: str
    risk_threshold: int          # score >= this -> BLOCK recommendation
    high_risk_threshold: int     # score >= this -> HIGH_RISK tier
    suspicious_threshold: int    # score >= this -> SUSPICIOUS tier
    monitor_threshold: int       # score >= this -> MONITOR (between ALLOW/BLOCK)
    signal_weights: Dict[str, int] = field(default_factory=dict)
    # Multiplier applied to confidence when evaluating MONITOR vs BLOCK.
    confidence_floor_for_block: int = 60
    description: str = ""

    def with_overrides(self, **overrides: Any) -> "Profile":
        return replace(self, **overrides)


# Default weight set; values are the raw additive contributions before clamping.
# Alias keys are kept for spec compatibility: spec lists both previous_suspicious_events
# and repeated_suspicious_events, and both number_format_anomaly and format_anomaly.
_DEFAULT_WEIGHTS: Dict[str, int] = {
    "blacklist_match": 80,
    "previous_block_events": 20,
    "repeated_suspicious_events": 15,
    "previous_suspicious_events": 15,
    "manual_user_report": 25,
    "format_anomaly": 5,
    "number_format_anomaly": 5,
    "rapid_repeat_events": 10,
    "reputation_history": 10,
}


PROFILES: Dict[str, Profile] = {
    "RELAXED": Profile(
        name="RELAXED",
        risk_threshold=80,
        high_risk_threshold=70,
        suspicious_threshold=45,
        monitor_threshold=30,
        signal_weights={**_DEFAULT_WEIGHTS, "format_anomaly": 3, "number_format_anomaly": 3, "rapid_repeat_events": 5},
        confidence_floor_for_block=75,
        description="Prefer fewer false positives; only strong evidence triggers BLOCK.",
    ),
    "BALANCED": Profile(
        name="BALANCED",
        risk_threshold=60,
        high_risk_threshold=60,
        suspicious_threshold=30,
        monitor_threshold=15,
        signal_weights=dict(_DEFAULT_WEIGHTS),
        confidence_floor_for_block=60,
        description="Normal protection with balanced sensitivity.",
    ),
    "STRICT": Profile(
        name="STRICT",
        risk_threshold=50,
        high_risk_threshold=50,
        suspicious_threshold=20,
        monitor_threshold=10,
        signal_weights={**_DEFAULT_WEIGHTS, "repeated_suspicious_events": 20, "previous_suspicious_events": 20,
                        "rapid_repeat_events": 15, "manual_user_report": 30},
        confidence_floor_for_block=45,
        description="Stronger blocking recommendations when evidence is solid.",
    ),
}


def get_profile(name: str) -> Profile:
    """Return the :class:`Profile` for ``name`` (case-insensitive)."""
    if not isinstance(name, str):
        raise KeyError("Profile name must be a string")
    key = name.upper()
    # Accept old synonyms from Phase 1.
    if key == "PERMISSIVE":
        key = "RELAXED"
    if key not in PROFILES:
        raise KeyError(
            f"Unknown profile '{name}'. Available: {', '.join(sorted(PROFILES))}."
        )
    return PROFILES[key]
