"""Privacy-preserving Phase 8 adaptive intelligence models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


ADAPTIVE_TRENDS = (
    "IMPROVING",
    "STABLE",
    "WORSENING",
    "VOLATILE",
    "INSUFFICIENT_DATA",
)


@dataclass(frozen=True)
class BehaviorObservation:
    event_id: str
    timestamp: str
    event_type: str
    risk_score: int
    confidence: int
    recommended_action: str
    applied_action: str
    confirmed: bool
    source: str
    trust_state: str = "UNKNOWN"
    trust_expires: Optional[str] = None
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BehaviorPattern:
    pattern_id: str
    evidence: Dict[str, Any]
    observation_count: int
    time_window_seconds: int
    confidence: int
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TrendResult:
    trend: str
    baseline_score: int
    current_score: int
    risk_delta: int
    confidence_delta: int
    sudden_change: bool
    direction_changes: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IntelligenceSnapshot:
    number_hash: str
    number_masked: str
    reputation_score: int = 0
    reputation_confidence: int = 0
    behavioral_trend: str = "INSUFFICIENT_DATA"
    patterns: List[BehaviorPattern] = field(default_factory=list)
    recent_observation_count: int = 0
    recent_high_risk_count: int = 0
    recent_block_recommendations: int = 0
    recent_user_reports: int = 0
    trust_state: str = "UNTRUSTED"
    trust_expiry: Optional[str] = None
    risk_delta: int = 0
    confidence_delta: int = 0
    baseline_score: int = 0
    current_score: int = 0
    explanations: List[str] = field(default_factory=list)
    observed: str = "UNKNOWN"
    recommended: str = "ALLOW"
    applied: str = "ALLOW"
    confirmed: bool = False
    available: bool = True
    error: Optional[str] = None
    timeline: List[BehaviorObservation] = field(default_factory=list)

    def to_public_dict(self, *, include_history: bool = False) -> Dict[str, Any]:
        value = {
            "number_masked": self.number_masked,
            "decision": (
                "BLOCK_RECOMMENDED" if self.recommended == "BLOCK" else "ALLOW_RECOMMENDED"
            ),
            "reputation_score": int(self.reputation_score),
            "reputation_confidence": int(self.reputation_confidence),
            "behavioral_trend": self.behavioral_trend,
            "patterns": [pattern.to_dict() for pattern in self.patterns],
            "recent_observation_count": int(self.recent_observation_count),
            "recent_high_risk_count": int(self.recent_high_risk_count),
            "recent_block_recommendations": int(self.recent_block_recommendations),
            "recent_user_reports": int(self.recent_user_reports),
            "trust_state": self.trust_state,
            "trust_expiry": self.trust_expiry,
            "risk_delta": int(self.risk_delta),
            "confidence_delta": int(self.confidence_delta),
            "baseline_score": int(self.baseline_score),
            "current_score": int(self.current_score),
            "explanations": list(self.explanations),
            "observed": self.observed,
            "recommended": self.recommended,
            "applied": self.applied,
            "confirmed": bool(self.confirmed),
            "available": bool(self.available),
            "error": self.error,
        }
        if include_history:
            value["history"] = [item.to_dict() for item in self.timeline]
        return value

    @classmethod
    def unavailable(
        cls, number_hash: str, number_masked: str, error: str
    ) -> "IntelligenceSnapshot":
        return cls(
            number_hash=number_hash,
            number_masked=number_masked,
            recommended="ALLOW",
            applied="ALLOW",
            behavioral_trend="INSUFFICIENT_DATA",
            available=False,
            error=str(error)[:200],
            explanations=["Adaptive intelligence unavailable; fail-open ALLOW"],
        )
