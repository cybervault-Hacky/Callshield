"""Fail-open Phase 5 policy engine and emergency switch helpers."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Mapping, Optional

from ..utils import safe_write_text
from .models import PolicyDecision
from .thresholds import PolicyConfigError, normalize_policy_name, thresholds_for_config


class PolicyError(RuntimeError):
    """Safe emergency-state operation could not be completed."""


class PolicyEngine:
    """Translate an existing detection result into an advisory policy decision.

    This class never touches Android or rejects a call. Invalid or uncertain
    state always returns an applied ALLOW decision.
    """

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def decide(
        self,
        detection: Any,
        *,
        whitelisted: Optional[bool] = None,
        mode: Optional[str] = None,
        screening_enabled: Optional[bool] = None,
        active_confirmed: Optional[bool] = None,
        policy_name: Optional[str] = None,
        emergency_off: Optional[bool] = None,
    ) -> PolicyDecision:
        selected_name = policy_name if policy_name is not None else getattr(
            self.cfg, "screening_policy", "BALANCED"
        )
        selected_mode = mode if mode is not None else getattr(
            self.cfg, "screening_mode", "DRY_RUN"
        )
        enabled = screening_enabled if screening_enabled is not None else getattr(
            self.cfg, "screening_enabled", False
        )
        confirmed = active_confirmed if active_confirmed is not None else getattr(
            self.cfg, "active_mode_confirmed", False
        )
        whitelist_match = (
            _is_whitelisted(detection) if whitelisted is None else bool(whitelisted)
        )
        risk = _score(detection, "risk_score", "risk")
        confidence = _score(detection, "confidence")

        try:
            normalized_policy = normalize_policy_name(selected_name)
            thresholds = thresholds_for_config(self.cfg, normalized_policy)
        except (PolicyConfigError, TypeError, ValueError):
            return _safe_error_decision(
                risk=risk,
                confidence=confidence,
                policy_name=str(selected_name or "INVALID"),
                mode=str(selected_mode or "INVALID"),
                reason="INVALID_POLICY_CONFIG",
                whitelisted=whitelist_match,
            )

        if not isinstance(selected_mode, str) or selected_mode not in ("DRY_RUN", "ACTIVE"):
            return _safe_error_decision(
                risk=risk,
                confidence=confidence,
                policy_name=normalized_policy,
                mode=str(selected_mode or "INVALID"),
                reason="INVALID_SCREENING_MODE",
                whitelisted=whitelist_match,
                threshold=thresholds.active_block,
                confidence_threshold=thresholds.confidence,
            )
        if not isinstance(enabled, bool) or not isinstance(confirmed, bool):
            return _safe_error_decision(
                risk=risk,
                confidence=confidence,
                policy_name=normalized_policy,
                mode=selected_mode,
                reason="INVALID_ACTIVATION_STATE",
                whitelisted=whitelist_match,
                threshold=thresholds.active_block,
                confidence_threshold=thresholds.confidence,
            )

        emergency = (
            is_emergency_off(self.cfg)
            if emergency_off is None
            else bool(emergency_off)
        )
        meets_thresholds = (
            risk >= thresholds.active_block
            and confidence >= thresholds.confidence
            and not whitelist_match
        )
        recommendation = "BLOCK" if meets_thresholds else "ALLOW"

        if whitelist_match:
            applied = "ALLOW"
            reason = "WHITELIST_OVERRIDE"
        elif emergency:
            applied = "ALLOW"
            reason = "EMERGENCY_OFF"
        elif not meets_thresholds:
            applied = "ALLOW"
            reason = "POLICY_THRESHOLDS_NOT_MET"
        elif not enabled:
            applied = "ALLOW"
            reason = "SCREENING_DISABLED"
        elif selected_mode == "DRY_RUN":
            applied = "ALLOW"
            reason = "DRY_RUN"
        elif not confirmed:
            applied = "ALLOW"
            reason = "ACTIVE_NOT_CONFIRMED"
        else:
            applied = "BLOCK"
            reason = "ACTIVE_POLICY_BLOCK"

        return PolicyDecision(
            recommended_action=recommendation,
            applied_action=applied,
            risk=risk,
            confidence=confidence,
            threshold=thresholds.active_block,
            confidence_threshold=thresholds.confidence,
            reason=reason,
            policy_name=normalized_policy,
            mode=selected_mode,
            screening_enabled=enabled,
            emergency_off=emergency,
            whitelisted=whitelist_match,
            policy_error=False,
        )


def emergency_path(cfg: Any) -> Path:
    configured = getattr(cfg, "emergency_off_file", None)
    if isinstance(configured, str) and configured.strip():
        return Path(configured).expanduser()
    return Path(getattr(cfg, "run_dir")).expanduser().parent / "state" / "emergency_off"


def is_emergency_off(cfg: Any) -> bool:
    """Treat any uncertain object at the emergency path as emergency ON."""

    path = emergency_path(cfg)
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return True


def enable_emergency_off(cfg: Any) -> bool:
    """Enable emergency-off idempotently with owner-only state."""

    path = emergency_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    if path.exists() or path.is_symlink():
        _require_owned_regular(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return False
    safe_write_text(path, "CALLSHIELD EMERGENCY OFF\n", mode=0o600)
    return True


def reset_emergency_off(cfg: Any) -> bool:
    """Remove only the owned emergency marker; never alter screening mode."""

    path = emergency_path(cfg)
    if not (path.exists() or path.is_symlink()):
        return False
    _require_owned_regular(path)
    try:
        path.unlink()
    except OSError as exc:
        raise PolicyError(f"Unable to reset emergency-off: {exc}") from exc
    return True


def _require_owned_regular(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PolicyError(f"Unable to inspect emergency state: {exc}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise PolicyError("Emergency state path is not a regular file")
    getuid = getattr(os, "geteuid", None)
    if getuid is not None and info.st_uid != getuid():
        raise PolicyError("Emergency state file is not owned by the current user")


def _score(detection: Any, *names: str) -> int:
    value: Any = None
    for name in names:
        if isinstance(detection, Mapping) and name in detection:
            value = detection[name]
            break
        if hasattr(detection, name):
            value = getattr(detection, name)
            break
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, min(100, int(value)))


def _is_whitelisted(detection: Any) -> bool:
    if isinstance(detection, Mapping):
        signals = detection.get("signals") or []
        reputation = detection.get("reputation")
        reason = detection.get("reason")
    else:
        signals = getattr(detection, "signals", []) or []
        reputation = getattr(detection, "reputation", None)
        reason = getattr(detection, "reason", None)
    for signal in signals:
        name = signal.get("name") if isinstance(signal, Mapping) else getattr(signal, "name", None)
        if name == "whitelist_match":
            return True
    return reputation == "TRUSTED" or reason == "User whitelist"


def _safe_error_decision(
    *,
    risk: int,
    confidence: int,
    policy_name: str,
    mode: str,
    reason: str,
    whitelisted: bool,
    threshold: int = 100,
    confidence_threshold: int = 100,
) -> PolicyDecision:
    return PolicyDecision(
        recommended_action="ALLOW",
        applied_action="ALLOW",
        risk=risk,
        confidence=confidence,
        threshold=threshold,
        confidence_threshold=confidence_threshold,
        reason=reason,
        policy_name=policy_name,
        mode=mode,
        screening_enabled=False,
        emergency_off=True,
        whitelisted=whitelisted,
        policy_error=True,
    )
