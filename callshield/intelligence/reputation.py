"""Advanced reputation engine for CALLSHIELD Phase 2.

This module implements the six-tier local reputation system used by the
rule engine and the CLI. It is purely local, deterministic and offline.

Reputation tiers (Phase 2):
    TRUSTED   — explicit whitelist, strong positive history
    SAFE      — no meaningful negative indicators
    UNKNOWN   — insufficient evidence
    SUSPICIOUS— some negative indicators
    HIGH_RISK — multiple strong indicators
    MALICIOUS — confirmed local malicious / blocked classification

The engine evaluates multiple signals (blacklist/whitelist membership,
stored reputation, historical events, user reports, weak pattern signals)
and maps them to a tier. Unknown numbers remain UNKNOWN — we never label
a number as fraudulent without positive local evidence.

The precedence rule WHITELIST > BLACKLIST > REPUTATION is enforced by the
callers (rules/engine). This module only classifies the reputation value;
it does not decide the final recommended action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .signals import SignalResult

# Local copy of thresholds to avoid circular import with rules.defaults
# Must stay in sync with rules/defaults.py
_TIER_THRESHOLDS = {
    "suspicious": 30,
    "high_risk": 60,
    "malicious": 85,
}


REPUTATION_LEVELS = ("TRUSTED", "SAFE", "UNKNOWN", "SUSPICIOUS", "HIGH_RISK", "MALICIOUS")

# Keep a legacy alias for Phase 1 (LOW/MEDIUM/HIGH/CRITICAL) if needed elsewhere.
LEGACY_MAP = {
    "LOW": "SAFE",
    "MEDIUM": "SUSPICIOUS",
    "HIGH": "HIGH_RISK",
    "CRITICAL": "MALICIOUS",
}


@dataclass
class ReputationResult:
    """Structured reputation outcome."""

    reputation: str
    score: int
    reason: str
    tier: str  # same as reputation for Phase 2, kept for clarity


def classify_reputation(
    *,
    whitelisted: bool,
    blacklisted: bool,
    risk_score: int,
    signals: List[SignalResult],
) -> ReputationResult:
    """Classify reputation from local signals and risk score.

    Deterministic, no network, no ML. Mirrors the logic in
    ``rules.engine._reputation_from_state`` so both paths stay consistent.
    """
    if whitelisted:
        has_history = any(s.name == "previous_block_events" for s in signals)
        rep = "TRUSTED" if not has_history else "SAFE"
        reason = "Explicit whitelist; no significant negative history" if rep == "TRUSTED" else "Explicit whitelist but prior negative history exists"
        return ReputationResult(reputation=rep, score=risk_score, reason=reason, tier=rep)

    if blacklisted:
        return ReputationResult(
            reputation="MALICIOUS",
            score=risk_score,
            reason="Confirmed local malicious — present in blacklist",
            tier="MALICIOUS",
        )

    if risk_score >= _TIER_THRESHOLDS["malicious"]:
        return ReputationResult(
            reputation="MALICIOUS",
            score=risk_score,
            reason="Risk score exceeds malicious threshold (strong local evidence)",
            tier="MALICIOUS",
        )
    if risk_score >= _TIER_THRESHOLDS["high_risk"]:
        return ReputationResult(
            reputation="HIGH_RISK",
            score=risk_score,
            reason="Multiple strong local indicators",
            tier="HIGH_RISK",
        )
    if risk_score >= _TIER_THRESHOLDS["suspicious"]:
        return ReputationResult(
            reputation="SUSPICIOUS",
            score=risk_score,
            reason="Some negative indicators present",
            tier="SUSPICIOUS",
        )
    if risk_score > 0:
        return ReputationResult(
            reputation="SAFE",
            score=risk_score,
            reason="No meaningful negative indicators (weak signals only)",
            tier="SAFE",
        )
    return ReputationResult(
        reputation="UNKNOWN",
        score=risk_score,
        reason="Insufficient local evidence",
        tier="UNKNOWN",
    )


def reputation_from_score(score: int) -> str:
    """Map a 0–100 risk score to a reputation tier (whitelist/blacklist excluded)."""
    if score >= _TIER_THRESHOLDS["malicious"]:
        return "MALICIOUS"
    if score >= _TIER_THRESHOLDS["high_risk"]:
        return "HIGH_RISK"
    if score >= _TIER_THRESHOLDS["suspicious"]:
        return "SUSPICIOUS"
    if score > 0:
        return "SAFE"
    return "UNKNOWN"


# Backwards-compatibility for any code importing from top-level reputation.py
__all__ = [
    "REPUTATION_LEVELS",
    "ReputationResult",
    "classify_reputation",
    "reputation_from_score",
]
