"""Event processor for CALLSHIELD through Phase 4.

The processor validates events, normalizes numbers, and delegates all fraud
analysis to the existing Phase 2 ``analyze_number`` API. Phase 5 then passes
incoming-call detections to the separate decision-only policy engine.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ..adaptive import BehaviorEngine, BehaviorObservation
from ..config import Config
from ..database import Database
from ..detector import analyze_number
from ..normalizer import normalize
from ..policy import PolicyEngine
from ..reputation import ReputationEngine
from ..utils import InvalidNumberError, mask_number
from .models import Event
from .types import EVENT_TYPE_INCOMING_CALL, VALID_EVENT_TYPES


class EventProcessor:
    """Process one event through the existing local detection pipeline."""

    def __init__(
        self,
        cfg: Config,
        db_path: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.cfg = cfg
        self.db_path = db_path or cfg.database_path
        self.logger = logger

    def _get_db(self) -> Database:
        return Database(self.db_path)

    def process(self, event: Event) -> Dict[str, Any]:
        if not isinstance(event, Event):
            raise ValueError("event must be an Event instance")
        event.validate(payload_limit=int(self.cfg.event_payload_limit))
        if event.event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {event.event_type}")

        started = time.monotonic()
        is_screening = event.event_type == EVENT_TYPE_INCOMING_CALL
        result: Dict[str, Any] = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "number": event.number,
            "status": "processed",
            "error": None,
            "detection": None,
        }

        if event.event_type in ("SYSTEM", "HEARTBEAT"):
            result["detection"] = {"verdict": "SYSTEM", "action": "NONE"}
            self._log_event(event, result)
            return result

        number = event.number
        if not number and isinstance(event.payload, dict):
            number = event.payload.get("number")
        if not number:
            if is_screening:
                self._set_screening_fallback(result, "MISSING_NUMBER", started)
            else:
                result["status"] = "failed"
                result["error"] = "Missing phone number"
            self._log_event(event, result)
            return result

        try:
            normalized = normalize(
                str(number), default_country=self.cfg.default_country
            ).normalized
        except InvalidNumberError as exc:
            if is_screening:
                self._set_screening_fallback(result, "INVALID_NUMBER", started)
            else:
                result["status"] = "failed"
                result["error"] = getattr(exc, "message", str(exc))
                result["detection"] = {"verdict": "INVALID", "action": "ALLOW"}
            self._log_event(event, result)
            return result
        except Exception as exc:
            if is_screening:
                self._set_screening_fallback(result, "NORMALIZATION_ERROR", started)
            else:
                result["status"] = "failed"
                result["error"] = f"Normalization failed: {exc}"
            self._log_event(event, result)
            return result

        database = None
        try:
            database = self._get_db()
            analysis = analyze_number(
                normalized,
                db=database,
                cfg=self.cfg,
                record_event=True,
            )
            result["detection"] = {
                "number": analysis.normalized_number,
                "risk_score": analysis.risk_score,
                "risk_level": analysis.risk_level,
                "confidence": analysis.confidence,
                "reputation": analysis.reputation,
                "verdict": analysis.verdict,
                "recommended_action": analysis.recommended_action,
                "reason": analysis.reason,
                "signals": analysis.signals,
            }
            if is_screening:
                reputation_profile = ReputationEngine(database, self.cfg).calculate(
                    normalized,
                    analysis=analysis,
                    persist=True,
                )
                reputation_data = reputation_profile.to_public_dict()
                result["reputation_profile"] = reputation_data
                result["detection"].update(
                    {
                        "trusted": reputation_profile.trusted,
                        "reputation_profile": reputation_data,
                        "reputation_error": not reputation_profile.available,
                        "reputation_trend": reputation_profile.trend,
                        "reputation_score": reputation_profile.risk_score,
                        "reputation_confidence": reputation_profile.confidence,
                    }
                )
                behavior_engine = BehaviorEngine(database, self.cfg)
                intelligence = behavior_engine.snapshot(
                    normalized,
                    reputation=reputation_profile,
                    detection=result["detection"],
                    observation=BehaviorObservation(
                        event_id=event.event_id,
                        timestamp=event.timestamp,
                        event_type="INCOMING_CALL",
                        risk_score=analysis.risk_score,
                        confidence=analysis.confidence,
                        recommended_action=analysis.recommended_action,
                        applied_action="UNKNOWN",
                        confirmed=False,
                        source=event.source,
                        trust_state=(
                            "TRUSTED" if reputation_profile.trusted else "UNTRUSTED"
                        ),
                        trust_expires=reputation_profile.trusted_until,
                        evidence={
                            "reputation_score": reputation_profile.risk_score,
                            "reputation_confidence": reputation_profile.confidence,
                            "user_reports": reputation_profile.user_reports,
                        },
                    ),
                    persist=True,
                )
                intelligence_data = intelligence.to_public_dict(include_history=False)
                result["intelligence"] = intelligence_data
                result["detection"].update(
                    {
                        "intelligence_context": intelligence_data,
                        "intelligence_error": not intelligence.available,
                    }
                )
                decision = PolicyEngine(self.cfg).decide(result["detection"])
                decision_data = decision.to_dict()
                behavior_engine.update_outcome(
                    event.event_id,
                    recommended_action=decision.recommended_action,
                    applied_action=decision.applied_action,
                )
                intelligence.recommended = decision.recommended_action
                intelligence.applied = decision.applied_action
                if intelligence.available:
                    behavior_engine.storage.save_snapshot(intelligence)
                    result["intelligence"] = intelligence.to_public_dict(
                        include_history=False
                    )
                latency_ms = _elapsed_ms(started)
                result["policy"] = decision_data
                result["detection"].update(
                    {
                        "detector_recommendation": analysis.recommended_action,
                        "recommended_action": decision.recommended_action,
                        "applied_action": decision.applied_action,
                        "mode": decision.mode,
                        "policy_name": decision.policy_name,
                        "threshold": decision.threshold,
                        "confidence_threshold": decision.confidence_threshold,
                        "emergency_off": decision.emergency_off,
                    }
                )
                result["screening"] = {
                    **decision_data,
                    "latency_ms": latency_ms,
                }
        except InvalidNumberError:
            if is_screening:
                self._set_screening_fallback(result, "INVALID_NUMBER", started)
            else:
                result["status"] = "failed"
                result["error"] = "Invalid phone number"
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = f"Detection failed: {exc}"
            if is_screening:
                self._set_screening_fallback(
                    result, "ANALYSIS_ERROR", started, keep_failed=True
                )
            if self.logger:
                try:
                    self.logger.exception(
                        "Failed to process event %s: %s", event.event_id, exc
                    )
                except Exception:
                    pass
        finally:
            if database is not None:
                try:
                    database.close()
                except Exception:
                    pass

        self._log_event(event, result)
        return result

    def _set_screening_fallback(
        self,
        result: Dict[str, Any],
        reason: str,
        started: float,
        keep_failed: bool = False,
    ) -> None:
        if not keep_failed:
            result["status"] = "processed"
            result["error"] = None
        result["detection"] = {
            "risk_score": 0,
            "confidence": 0,
            "verdict": "UNKNOWN",
            "recommended_action": "ALLOW",
            "applied_action": "ALLOW",
            "mode": "DRY_RUN",
            "reason": reason,
        }
        result["policy"] = {
            "recommended_action": "ALLOW",
            "applied_action": "ALLOW",
            "risk": 0,
            "confidence": 0,
            "threshold": 100,
            "confidence_threshold": 100,
            "reason": reason,
            "policy_name": str(getattr(self.cfg, "screening_policy", "BALANCED")),
            "mode": "DRY_RUN",
            "screening_enabled": False,
            "emergency_off": True,
            "whitelisted": False,
            "policy_error": True,
        }
        result["screening"] = {
            **result["policy"],
            "latency_ms": _elapsed_ms(started),
        }

    def _log_event(self, event: Event, result: Dict[str, Any]) -> None:
        if not self.logger:
            return
        try:
            masked = mask_number(event.number) if event.number else "N/A"
            detection = result.get("detection") or {}
            self.logger.info(
                "event %s type=%s number=%s status=%s verdict=%s recommended=%s applied=%s",
                event.event_id,
                event.event_type,
                masked,
                result.get("status"),
                detection.get("verdict", "N/A"),
                detection.get("recommended_action", detection.get("action", "N/A")),
                detection.get("applied_action", "N/A"),
            )
        except Exception:
            pass


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))
