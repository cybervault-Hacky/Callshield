"""Structured, privacy-preserving Phase 7 reputation models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


RISK_LEVELS = ("TRUSTED", "LOW", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN")
TRENDS = ("IMPROVING", "STABLE", "WORSENING", "UNKNOWN")


@dataclass(frozen=True)
class ReputationSignal:
    name: str
    score_delta: int
    confidence: int
    measurement: int
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReputationHistoryEntry:
    timestamp: str
    old_score: Optional[int]
    new_score: int
    risk_before: Optional[str]
    risk_after: str
    trigger: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReputationProfile:
    number_hash: str
    number_masked: str
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    calls_seen: int = 0
    calls_answered: int = 0
    calls_rejected: int = 0
    calls_allowed: int = 0
    block_recommendations: int = 0
    user_reports: int = 0
    risk_score: int = 0
    confidence: int = 0
    risk: str = "UNKNOWN"
    trend: str = "UNKNOWN"
    trusted: bool = False
    trusted_until: Optional[str] = None
    signals: List[ReputationSignal] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    history: List[ReputationHistoryEntry] = field(default_factory=list)
    recommendation: str = "ALLOW"
    available: bool = True
    error: Optional[str] = None

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "number_masked": self.number_masked,
            "risk": self.risk,
            "score": int(self.risk_score),
            "confidence": int(self.confidence),
            "trend": self.trend,
            "trusted": bool(self.trusted),
            "trusted_until": self.trusted_until,
            "signals": [signal.to_dict() for signal in self.signals],
            "reasons": list(self.reasons),
            "history": {
                "first_seen": self.first_seen,
                "last_seen": self.last_seen,
                "calls_seen": int(self.calls_seen),
                "calls_answered": int(self.calls_answered),
                "calls_rejected": int(self.calls_rejected),
                "calls_allowed": int(self.calls_allowed),
                "block_recommendations": int(self.block_recommendations),
                "user_reports": int(self.user_reports),
                "changes": [entry.to_dict() for entry in self.history],
            },
            "recommendation": self.recommendation,
            "available": bool(self.available),
            "error": self.error,
        }

    @classmethod
    def unavailable(cls, number_hash: str, number_masked: str, error: str) -> "ReputationProfile":
        return cls(
            number_hash=number_hash,
            number_masked=number_masked,
            risk="UNKNOWN",
            trend="UNKNOWN",
            recommendation="ALLOW",
            available=False,
            error=str(error)[:200],
            reasons=["Reputation unavailable; fail-open ALLOW"],
        )


@dataclass(frozen=True)
class TrustedRecord:
    number_hash: str
    number_masked: str
    created_at: str
    expires_at: Optional[str]
    note: Optional[str] = None

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "number_masked": self.number_masked,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "note": self.note,
        }
