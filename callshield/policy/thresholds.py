"""Validated Phase 5 active-protection policy thresholds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


class PolicyConfigError(ValueError):
    """A policy name or threshold is invalid; callers must fail open."""


@dataclass(frozen=True)
class PolicyThresholds:
    active_block: int
    confidence: int

    def validate(self) -> "PolicyThresholds":
        for name, value in (
            ("active_block", self.active_block),
            ("confidence", self.confidence),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= 100):
                raise PolicyConfigError(f"{name} threshold must be an integer from 0 to 100")
        return self


DEFAULT_POLICIES: Dict[str, PolicyThresholds] = {
    "RELAXED": PolicyThresholds(active_block=92, confidence=90),
    "BALANCED": PolicyThresholds(active_block=85, confidence=80),
    "STRICT": PolicyThresholds(active_block=80, confidence=75),
}


def normalize_policy_name(value: Any) -> str:
    if not isinstance(value, str):
        raise PolicyConfigError("policy name must be a string")
    name = value.strip().upper()
    if name not in DEFAULT_POLICIES:
        raise PolicyConfigError(
            f"unknown policy '{value}'; expected RELAXED, BALANCED, or STRICT"
        )
    return name


def thresholds_for_config(cfg: Any, policy_name: Any = None) -> PolicyThresholds:
    """Read the selected policy's configurable values from ``cfg``."""

    name = normalize_policy_name(
        policy_name if policy_name is not None else getattr(cfg, "screening_policy", None)
    )
    prefix = name.lower()
    defaults = DEFAULT_POLICIES[name]
    thresholds = PolicyThresholds(
        active_block=getattr(
            cfg, f"{prefix}_active_block_threshold", defaults.active_block
        ),
        confidence=getattr(
            cfg, f"{prefix}_confidence_threshold", defaults.confidence
        ),
    )
    return thresholds.validate()
