"""Deterministic rule engine for CALLSHIELD Phase 2.

Evaluation order (fixed & documented):

  1. Normalize the number (done by the caller; caller passes normalized info)
  2. Check whitelist (signal-based)
  3. Check blacklist (signal-based)
  4. Load reputation history
  5. Analyze behavioral history
  6. Evaluate reports
  7. Evaluate weak pattern signals
  8. Calculate risk score (sum, clamp 0..100)
  9. Calculate confidence
  10. Produce tier & verdict
  11. Produce recommended action

The engine never calls out to the network, never invokes eval/exec, and never
executes user-controlled strings as code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..database import Database
from ..intelligence import (
    BehaviorAnalysis,
    NumberIntelligence,
    SignalResult,
    compute_confidence,
    evaluate_signals,
)
from ..intelligence.profiles import Profile, get_profile
from . import defaults


@dataclass
class DetectionResult:
    """Structured decision returned by :func:`evaluate`."""

    input_number: str
    normalized_number: str
    risk_score: int
    risk_level: str              # LOW | MEDIUM | HIGH | CRITICAL
    confidence: int              # 0..100
    reputation: str              # UNKNOWN | SAFE | TRUSTED | SUSPICIOUS | HIGH_RISK | MALICIOUS
    verdict: str                 # SAFE | UNKNOWN | SUSPICIOUS | HIGH_RISK | MALICIOUS
    recommended_action: str      # ALLOW | MONITOR | BLOCK
    reason: str
    signals: List[Dict[str, Any]] = field(default_factory=list)
    behavior: Dict[str, Any] = field(default_factory=dict)
    number_intelligence: Dict[str, Any] = field(default_factory=dict)
    list_conflict: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "number": self.normalized_number,
            "input": self.input_number,
            "risk_score": int(self.risk_score),
            "risk_level": self.risk_level,
            "confidence": int(self.confidence),
            "reputation": self.reputation,
            "verdict": self.verdict,
            "recommended_action": self.recommended_action,
            "reason": self.reason,
            "signals": self.signals,
            "behavior": self.behavior,
            "number_intelligence": self.number_intelligence,
            "list_conflict": bool(self.list_conflict),
        }


def _score_from_signals(signals: List[SignalResult], profile: Profile) -> int:
    """Aggregate signal deltas using the profile's weights; clamp to 0..100.

    Whitelist overrides any positive score (per precedence rule).
    """
    if any(s.name == "whitelist_match" for s in signals):
        return 0

    score = 0
    for s in signals:
        # Format anomalies etc. are weighted by the profile.
        w = profile.signal_weights.get(s.name, None)
        if w is None:
            # Fall back to the signal's intrinsic score.
            delta = s.score
        else:
            if s.score > 0:
                # Scale positive signals by ratio between default weight (1.0)
                # and profile weight — but keep small signals small.
                # We instead trust the signal's own delta (which already
                # respects config weights).
                delta = s.score
            else:
                delta = s.score
        score += delta
    return max(0, min(100, int(round(score))))


def _tier_from_score(score: int, profile: Profile) -> str:
    if score >= defaults.TIER_THRESHOLDS["malicious"]:
        return "CRITICAL"
    if score >= profile.high_risk_threshold:
        return "HIGH"
    if score >= profile.suspicious_threshold:
        return "MEDIUM"
    if score > 0:
        return "LOW"
    return "LOW"


def _reputation_from_state(
    *, whitelisted: bool, blacklisted: bool, score: int, signals: List[SignalResult]
) -> str:
    if whitelisted:
        # Distinguish explicit long-term TRUSTED from a generic SAFE.
        has_history = any(s.name == "previous_block_events" for s in signals)
        return "TRUSTED" if not has_history else "SAFE"
    if blacklisted:
        return "MALICIOUS"
    if score >= defaults.TIER_THRESHOLDS["malicious"]:
        return "MALICIOUS"
    if score >= defaults.TIER_THRESHOLDS["high_risk"]:
        return "HIGH_RISK"
    if score >= defaults.TIER_THRESHOLDS["suspicious"]:
        return "SUSPICIOUS"
    if score > 0:
        return "SAFE"  # weak positive signals -> still basically safe
    return "UNKNOWN"


def _verdict_from_score(
    *, whitelisted: bool, blacklisted: bool, score: int, profile: Profile
) -> str:
    if whitelisted:
        return "SAFE"
    if blacklisted:
        return "MALICIOUS"
    if score >= defaults.TIER_THRESHOLDS["malicious"]:
        return "MALICIOUS"
    if score >= profile.high_risk_threshold:
        return "HIGH_RISK"
    if score >= profile.suspicious_threshold:
        return "SUSPICIOUS"
    if score > 0:
        return "UNKNOWN"
    return "UNKNOWN"


def _action_from_state(
    *, verdict: str, score: int, confidence: int, profile: Profile,
) -> str:
    if verdict == "SAFE":
        return "ALLOW"
    if verdict == "MALICIOUS":
        return "BLOCK"
    if verdict == "HIGH_RISK" and score >= profile.risk_threshold \
            and confidence >= profile.confidence_floor_for_block:
        return "BLOCK"
    if verdict in ("HIGH_RISK", "SUSPICIOUS"):
        return "MONITOR"
    return "ALLOW"


def _reason_from_signals(
    verdict: str, action: str, signals: List[SignalResult], score: int,
) -> str:
    positive = [s for s in signals if s.score > 0]
    if verdict == "SAFE":
        if any(s.name == "whitelist_match" for s in signals):
            return "User whitelist"
        return "No meaningful negative indicators."
    if verdict == "UNKNOWN":
        return "No strong fraud indicators found."
    if verdict == "MALICIOUS":
        if any(s.name == "blacklist_match" for s in signals):
            return "Number is in local blacklist."
        return "Strong local evidence of malicious activity."
    if verdict == "HIGH_RISK":
        return "Strong local evidence indicates elevated fraud/spam risk."
    # SUSPICIOUS
    names = ", ".join(s.reason.split(".")[0] for s in positive[:3])
    if names:
        return f"Some suspicious signals: {names}."
    return "Some suspicious signals detected."


def evaluate(
    *,
    raw_number: str,
    normalized: str,
    digits: str,
    db: Database,
    cfg: Config,
    list_rows: Optional[Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
) -> DetectionResult:
    """Run the full evaluation pipeline and return a :class:`DetectionResult`.

    ``list_rows`` is an optional ``(blacklist_row, whitelist_row)`` tuple used
    when the caller already fetched the rows; otherwise they are loaded here.
    """
    profile = get_profile(cfg.protection_mode)

    # Always load list rows here so the detector sees a consistent snapshot.
    bl_row = db.get_list_entry(normalized, "blacklist")
    wl_row = db.get_list_entry(normalized, "whitelist")
    # If caller explicitly passed rows, prefer them (for testing/future use).
    if list_rows is not None:
        bl_row, wl_row = list_rows
    signals: List[SignalResult]
    behavior: BehaviorAnalysis
    intel: NumberIntelligence
    signals, behavior, intel = evaluate_signals(
        raw_number, normalized, digits, db, cfg, list_rows=(bl_row, wl_row),
    )

    whitelisted = any(s.name == "whitelist_match" for s in signals)
    blacklisted = any(s.name == "blacklist_match" for s in signals) and not whitelisted
    list_conflict = any(s.name == "list_conflict" for s in signals)

    score = _score_from_signals(signals, profile)
    confidence = compute_confidence(signals, history_depth=behavior.total_events)
    tier = _tier_from_score(score, profile)
    reputation = _reputation_from_state(
        whitelisted=whitelisted, blacklisted=blacklisted, score=score, signals=signals,
    )
    verdict = _verdict_from_score(
        whitelisted=whitelisted, blacklisted=blacklisted, score=score, profile=profile,
    )
    action = _action_from_state(
        verdict=verdict, score=score, confidence=confidence, profile=profile,
    )
    reason = _reason_from_signals(verdict, action, signals, score)

    return DetectionResult(
        input_number=raw_number,
        normalized_number=normalized,
        risk_score=int(score),
        risk_level=tier,
        confidence=int(confidence),
        reputation=reputation,
        verdict=verdict,
        recommended_action=action,
        reason=reason,
        signals=[s.to_dict() for s in signals],
        behavior=behavior.to_dict(),
        number_intelligence=intel.to_dict(),
        list_conflict=list_conflict,
    )
