"""Event processor for CALLSHIELD Phase 3.

Validates, normalizes, calls the Phase 2 detector, persists results,
writes logs, and updates daemon metrics. Remains independent of daemon threading.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from ..config import Config
from ..database import Database
from ..detector import analyze_number
from ..normalizer import normalize
from ..utils import InvalidNumberError, iso_now, mask_number
from .models import Event
from .types import VALID_EVENT_TYPES


class EventProcessor:
    """Processes a single Event through the detection pipeline."""

    def __init__(self, cfg: Config, db_path: Optional[str] = None, logger: Optional[logging.Logger] = None) -> None:
        self.cfg = cfg
        self.db_path = db_path or cfg.database_path
        self.logger = logger

    def _get_db(self) -> Database:
        return Database(self.db_path)

    def process(self, event: Event) -> Dict[str, Any]:
        """Process an event and return a result dict.

        Steps:
        1. validate event
        2. normalize number when present
        3. call Phase 2 detector
        4. persist event/result
        5. write security log
        6. return structured result
        """
        if not isinstance(event, Event):
            raise ValueError("event must be an Event instance")
        # Revalidate at the processing boundary. This catches objects mutated
        # after construction and applies the configured (possibly stricter)
        # payload limit without trusting an IPC caller.
        event.validate(payload_limit=int(self.cfg.event_payload_limit))
        if event.event_type not in VALID_EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {event.event_type}")

        result: Dict[str, Any] = {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "number": event.number,
            "status": "processed",
            "error": None,
            "detection": None,
        }

        # For events without a number (SYSTEM, HEARTBEAT), just log and return
        if event.event_type in ("SYSTEM", "HEARTBEAT"):
            result["status"] = "processed"
            result["detection"] = {"verdict": "SYSTEM", "action": "NONE"}
            self._log_event(event, result)
            return result

        # Events that require a number
        number = event.number
        if not number:
            # Try payload number
            number = event.payload.get("number") if isinstance(event.payload, dict) else None

        if not number:
            result["status"] = "failed"
            result["error"] = "Missing phone number"
            self._log_event(event, result)
            return result

        # Normalize
        try:
            norm = normalize(str(number), default_country=self.cfg.default_country)
            normalized = norm.normalized
        except InvalidNumberError as exc:
            result["status"] = "failed"
            result["error"] = str(exc.message) if hasattr(exc, 'message') else str(exc)
            result["detection"] = {"verdict": "INVALID", "action": "ALLOW"}
            self._log_event(event, result)
            return result
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = f"Normalization failed: {exc}"
            self._log_event(event, result)
            return result

        # Call detector (Phase 2)
        try:
            db = self._get_db()
            try:
                analysis = analyze_number(normalized, db=db, cfg=self.cfg, record_event=True)
            finally:
                db.close()
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
            # Update metrics-like fields in result
            result["status"] = "processed"
        except InvalidNumberError as exc:
            result["status"] = "failed"
            result["error"] = str(exc.message) if hasattr(exc, 'message') else str(exc)
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = f"Detection failed: {exc}"
            if self.logger:
                self.logger.exception(f"Failed to process event {event.event_id}: {exc}")

        self._log_event(event, result)
        return result

    def _log_event(self, event: Event, result: Dict[str, Any]) -> None:
        if self.logger:
            try:
                masked = mask_number(event.number) if event.number else "N/A"
                self.logger.info(
                    f"event {event.event_id} type={event.event_type} number={masked} status={result.get('status')} verdict={result.get('detection', {}).get('verdict') if result.get('detection') else 'N/A'}"
                )
            except Exception:
                pass
