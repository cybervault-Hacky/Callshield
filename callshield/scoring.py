"""Deterministic, explainable risk scoring.

Score range: 0 – 100.
Tiers:
    0–29  LOW        (safe / unknown)
   30–59  MEDIUM     (caution)
   60–79  HIGH       (likely unwanted)
  80–100  CRITICAL   (block)

Whitelist forces a score of 0. Blacklist contributes a large positive weight.
Additional signals add smaller additive weights. All contributions are clamped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from .reputation import ReputationSignals


@dataclass
class ScoreBreakdown:
    """Explained risk score."""

    score: int = 0
    level: str = "LOW"
    signals: List[Tuple[str, int, str]] = field(default_factory=list)
    # Each signal entry: (label, delta, reason)

    def add(self, label: str, delta: int, reason: str = "") -> None:
        self.signals.append((label, delta, reason))


def _level_for(score: int) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    if score > 0:
        return "LOW"
    return "LOW"  # 0 -> LOW but treated as UNKNOWN by caller when there are no signals


def compute_score(sig: ReputationSignals) -> ScoreBreakdown:
    """Compute an explained score for the given reputation signals."""
    brk = ScoreBreakdown()
    score = 0

    # Precedence rule: WHITELIST > BLACKLIST > REPUTATION.
    if sig.in_whitelist:
        brk.add("Whitelist match", -100, "Number explicitly allowed by user")
        score = 0
        if sig.in_blacklist:
            brk.add(
                "List conflict",
                0,
                "Number is in BOTH lists; whitelist takes precedence by documented rule",
            )
        brk.score = 0
        brk.level = "LOW"
        return brk

    if sig.in_blacklist:
        brk.add("Blacklist match", +80, "Number explicitly blocked by user")
        score += 80

    # Previous suspicious events — small linear bump, capped.
    if sig.previous_suspicious > 0:
        delta = min(5 * sig.previous_suspicious, 15)
        brk.add(
            f"Previous suspicious events ({sig.previous_suspicious})",
            +delta,
            "Seen flagged in prior analyses",
        )
        score += delta

    # Stored reputation (if set explicitly or by prior runs)
    rep = sig.stored_reputation
    rep_weights = {
        "LOW": 5,
        "MEDIUM": 15,
        "HIGH": 35,
        "CRITICAL": 50,
    }
    if rep in rep_weights and not sig.in_blacklist:
        # Don't double-count if blacklist already applied.
        w = rep_weights[rep]
        brk.add(f"Stored reputation ({rep})", +w, "Previously recorded reputation")
        score += w

    # Clamp
    score = max(0, min(100, score))

    # If there were no signals at all, the number is UNKNOWN (score 0).
    brk.score = score
    brk.level = _level_for(score)
    return brk


def verdict_for(brk: ScoreBreakdown, sig: ReputationSignals, threshold: int) -> Tuple[str, str, str]:
    """Return (verdict, recommended_action, reason) based on breakdown.

    Precedence: whitelist -> blacklist -> score threshold.
    """
    if sig.in_whitelist:
        return ("SAFE", "ALLOW", "User whitelist")
    if sig.in_blacklist:
        return ("HIGH_RISK", "BLOCK", "User blacklist")

    score = brk.score
    if score >= threshold and threshold <= 79:
        # At strict thresholds a HIGH score also triggers a block recommendation.
        return ("HIGH_RISK", "BLOCK", f"Score {score} >= threshold {threshold}")
    if score >= 80:
        return ("HIGH_RISK", "BLOCK", "Critical risk score")
    if score >= 60:
        return ("MEDIUM_RISK", "REVIEW", "Elevated risk score")
    if score >= 30:
        return ("MEDIUM_RISK", "CAUTION", "Some suspicious signals")
    if score > 0:
        return ("LOW_RISK", "ALLOW", "Minor signals only")
    return ("UNKNOWN", "ALLOW", "No strong fraud indicators found")
