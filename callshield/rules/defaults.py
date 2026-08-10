"""Default thresholds and labels consumed by the rule engine."""

from __future__ import annotations

from typing import Dict, Tuple

# Score tiers (after clamping 0..100).
#   < threshold_suspicious     -> SAFE/UNKNOWN
#   >= threshold_suspicious    -> SUSPICIOUS
#   >= threshold_high_risk     -> HIGH_RISK
#   >= threshold_malicious     -> MALICIOUS
#
# These defaults apply if a profile does not override them; profiles may use
# different values.
TIER_THRESHOLDS: Dict[str, int] = {
    "suspicious": 30,
    "high_risk": 60,
    "malicious": 85,
}

# Action mapping per (verdict, confidence, profile). Kept as constants for
# documentation; the actual logic lives in engine.py.
VERDICT_LABELS: Tuple[str, ...] = (
    "SAFE",
    "UNKNOWN",
    "SUSPICIOUS",
    "HIGH_RISK",
    "MALICIOUS",
)

ACTIONS: Tuple[str, ...] = ("ALLOW", "MONITOR", "BLOCK")

# Human-readable reasons for each verdict (generic; signals provide specifics).
GENERIC_REASONS: Dict[str, str] = {
    "SAFE": "Explicitly trusted (whitelist).",
    "UNKNOWN": "No strong fraud indicators found.",
    "SUSPICIOUS": "Some suspicious signals detected; exercise caution.",
    "HIGH_RISK": "Strong local evidence indicates elevated fraud/spam risk.",
    "MALICIOUS": "Strong confirmed local evidence of malicious activity.",
}
