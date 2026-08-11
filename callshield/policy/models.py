"""Structured policy decisions for Phase 5."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class PolicyDecision:
    recommended_action: str
    applied_action: str
    risk: int
    confidence: int
    threshold: int
    confidence_threshold: int
    reason: str
    policy_name: str
    mode: str
    screening_enabled: bool
    emergency_off: bool
    whitelisted: bool
    policy_error: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def applies_block(self) -> bool:
        return self.applied_action == "BLOCK"
