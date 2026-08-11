"""Event processor for CALLSHIELD through Phase 4.

The processor validates events, normalizes numbers, and delegates all fraud
analysis to the existing Phase 2 ``analyze_number`` API.  Phase 4 adds only an
advisory incoming-call result; it never applies a blocking action.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from ..config import Config
from ..database import Database
from ..detector import analyze_number
from ..normalizer import normalize
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
            recommendation = analysis.recommended_action
            if is_screening and recommendation not in ("ALLOW", "BLOCK"):
                recommendation = "UNKNOWN"
            result["detection"] = {
                "number": analysis.normalized_number,
                "risk_score": analysis.risk_score,
                "risk_level": analysis.risk_level,
                "confidence": analysis.confidence,
                "reputation": analysis.reputation,
                "verdict": analysis.verdict,
                "recommended_action": recommendation,
                "reason": analysis.reason,
                "signals": analysis.signals,
            }
            if is_screening:
                latency_ms = _elapsed_ms(started)
                result["detection"].update(
                    {
                        "applied_action": "ALLOW",
                        "mode": "DRY_RUN",
                    }
                )
                result["screening"] = {
                    "recommended_action": recommendation,
                    "applied_action": "ALLOW",
                    "mode": "DRY_RUN",
                    "reason": "DRY_RUN" if recommendation == "BLOCK" else analysis.reason,
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

    @staticmethod
    def _set_screening_fallback(
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
        result["screening"] = {
            "recommended_action": "ALLOW",
            "applied_action": "ALLOW",
            "mode": "DRY_RUN",
            "reason": reason,
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
