"""Structured, non-fabricating universal number profile."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

AVAILABILITY = ("AVAILABLE", "NOT_AVAILABLE", "NOT_VERIFIED", "UNKNOWN")


@dataclass(frozen=True)
class FieldValue:
    """One profile field with an explicit availability tag."""

    value: Any
    availability: str = "UNKNOWN"

    def to_public(self) -> Dict[str, Any]:
        return {"value": self.value, "availability": self.availability}


def tagged(value: Any, availability: str) -> FieldValue:
    if availability not in AVAILABILITY:
        availability = "UNKNOWN"
    return FieldValue(value=value, availability=availability)


def unavailable(label: str = "NOT_AVAILABLE") -> FieldValue:
    return FieldValue(value=label, availability="NOT_AVAILABLE")


def unknown(label: str = "UNKNOWN") -> FieldValue:
    return FieldValue(value=label, availability="UNKNOWN")


def not_verified(label: str = "NOT_VERIFIED") -> FieldValue:
    return FieldValue(value=label, availability="NOT_VERIFIED")


def available(value: Any) -> FieldValue:
    return FieldValue(value=value, availability="AVAILABLE")


@dataclass
class UniversalNumberProfile:
    """Local-only composite view of one number. Never invents identity."""

    normalized_number: FieldValue
    masked_number: FieldValue
    country: FieldValue
    region: FieldValue
    local_contact_status: FieldValue
    contact_name: FieldValue
    age: FieldValue
    owner_identity: FieldValue
    reputation_score: FieldValue
    reputation_confidence: FieldValue
    risk_level: FieldValue
    verdict: FieldValue
    recommendation: FieldValue
    trust_state: FieldValue
    first_seen: FieldValue
    last_seen: FieldValue
    calls_observed: FieldValue
    reports: FieldValue
    historical_block_recommendations: FieldValue
    behavioral_trend: FieldValue
    intelligence_patterns: FieldValue
    measured_evidence: FieldValue
    data_sources: FieldValue
    contact_source: FieldValue = field(
        default_factory=lambda: unavailable("NOT_AVAILABLE")
    )
    valid: bool = True
    available: bool = True
    error: Optional[str] = None

    def to_public_dict(self) -> Dict[str, Any]:
        public: Dict[str, Any] = {
            "valid": bool(self.valid),
            "available": bool(self.available),
            "error": self.error,
        }
        for name in (
            "masked_number",
            "country",
            "region",
            "local_contact_status",
            "contact_name",
            "age",
            "owner_identity",
            "reputation_score",
            "reputation_confidence",
            "risk_level",
            "verdict",
            "recommendation",
            "trust_state",
            "first_seen",
            "last_seen",
            "calls_observed",
            "reports",
            "historical_block_recommendations",
            "behavioral_trend",
            "intelligence_patterns",
            "measured_evidence",
            "data_sources",
            "contact_source",
        ):
            field_value = getattr(self, name)
            public[name] = field_value.to_public() if isinstance(field_value, FieldValue) else field_value
        return public

    @classmethod
    def invalid(cls, reason: str) -> "UniversalNumberProfile":
        missing = unavailable("NOT_AVAILABLE")
        return cls(
            normalized_number=unavailable("NOT_AVAILABLE"),
            masked_number=unavailable("NOT_AVAILABLE"),
            country=missing,
            region=missing,
            local_contact_status=available("NOT SAVED"),
            contact_name=unavailable("NOT AVAILABLE"),
            age=unavailable("NOT AVAILABLE"),
            owner_identity=not_verified("NOT VERIFIED"),
            reputation_score=unknown("UNKNOWN"),
            reputation_confidence=unknown("UNKNOWN"),
            risk_level=unknown("UNKNOWN"),
            verdict=unknown("UNKNOWN"),
            recommendation=available("ALLOW"),
            trust_state=unknown("UNKNOWN"),
            first_seen=unavailable("NOT AVAILABLE"),
            last_seen=unavailable("NOT AVAILABLE"),
            calls_observed=available(0),
            reports=available(0),
            historical_block_recommendations=available(0),
            behavioral_trend=unknown("UNKNOWN"),
            intelligence_patterns=unavailable("NOT AVAILABLE"),
            measured_evidence=unavailable("NOT AVAILABLE"),
            data_sources=available(["LOCAL ONLY"]),
            valid=False,
            available=False,
            error=str(reason)[:200],
        )


__all__ = [
    "AVAILABILITY",
    "FieldValue",
    "UniversalNumberProfile",
    "available",
    "not_verified",
    "tagged",
    "unavailable",
    "unknown",
]
