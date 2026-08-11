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

        # Detect if this is a screening event (INCOMING_CALL) vs regular scan
        is_screening = event.event_type == "INCOMING_CALL"
        start_ts = __import__("time").time()

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
            if is_screening:
                result["detection"] = {"verdict": "UNKNOWN", "recommended_action": "ALLOW", "applied_action": "ALLOW", "mode": "DRY_RUN", "reason": "Invalid number", "risk_score": 0, "confidence": 0}
                result["screening"] = {"recommended_action": "ALLOW", "applied_action": "ALLOW", "mode": "DRY_RUN", "latency_ms": int((__import__("time").time() - start_ts) * 1000)}
                try:
                    db2 = self._get_db()
                    try:
                        db2.add_screening_event(
                            timestamp=event.timestamp,
                            number=str(number) or "unknown",
                            risk_score=0,
                            confidence=0,
                            verdict="UNKNOWN",
                            recommended_action="ALLOW",
                            applied_action="ALLOW",
                            result_reason="INVALID_NUMBER",
                            latency_ms=result["screening"]["latency_ms"],
                            source=event.source,
                            event_id=event.event_id,
                        )
                    finally:
                        db2.close()
                except Exception:
                    pass
            else:
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
            result["status"] = "processed"
            # For screening events, apply dry-run logic and persist screening_event
            if is_screening:
                import time as _t
                latency_ms = int((_t.time() - start_ts) * 1000)
                recommended = analysis.recommended_action
                # Phase 4 dry-run: applied always ALLOW, even if recommended BLOCK
                mode = getattr(self.cfg, "screening_mode", "DRY_RUN")
                applied = "ALLOW"  # Phase 4 always ALLOW
                if mode != "DRY_RUN":
                    # Future Phase 5 would allow BLOCK, but Phase 4 forces DRY_RUN
                    applied = "ALLOW"
                result["screening"] = {
                    "recommended_action": recommended,
                    "applied_action": applied,
                    "mode": "DRY_RUN",
                    "latency_ms": latency_ms,
                }
                result["detection"]["applied_action"] = applied
                result["detection"]["mode"] = "DRY_RUN"
                # Persist screening event
                try:
                    db2 = self._get_db()
                    try:
                        db2.add_screening_event(
                            timestamp=event.timestamp,
                            number=normalized,
                            risk_score=analysis.risk_score,
                            confidence=analysis.confidence,
                            verdict=analysis.verdict,
                            recommended_action=recommended,
                            applied_action=applied,
                            result_reason="DRY_RUN" if recommended == "BLOCK" else analysis.reason,
                            latency_ms=latency_ms,
                            source=event.source,
                            event_id=event.event_id,
                        )
                    finally:
                        db2.close()
                except Exception as e:
                    if self.logger:
                        self.logger.error(f"Failed to persist screening event: {e}")
                # Also log screening event nicely
                if self.logger:
                    try:
                        self.logger.info(
                            f"SCREENING event={event.event_id} number={mask_number(normalized)} risk={analysis.risk_score} verdict={analysis.verdict} rec={recommended} applied={applied} mode=DRY_RUN latency={latency_ms}ms"
                        )
                    except Exception:
                        pass
        except InvalidNumberError as exc:
            result["status"] = "failed"
            result["error"] = str(exc.message) if hasattr(exc, 'message') else str(exc)
            if is_screening:
                # For screening, even invalid numbers should return ALLOW with UNKNOWN
                result["detection"] = {
                    "risk_score": 0,
                    "confidence": 0,
                    "verdict": "UNKNOWN",
                    "recommended_action": "ALLOW",
                    "applied_action": "ALLOW",
                    "mode": "DRY_RUN",
                    "reason": "Invalid number",
                }
                result["screening"] = {
                    "recommended_action": "ALLOW",
                    "applied_action": "ALLOW",
                    "mode": "DRY_RUN",
                    "latency_ms": int((__import__("time").time() - start_ts) * 1000),
                }
                try:
                    db2 = self._get_db()
                    try:
                        db2.add_screening_event(
                            timestamp=event.timestamp,
                            number=number or "unknown",
                            risk_score=0,
                            confidence=0,
                            verdict="UNKNOWN",
                            recommended_action="ALLOW",
                            applied_action="ALLOW",
                            result_reason="INVALID_NUMBER",
                            latency_ms=result["screening"]["latency_ms"],
                            source=event.source,
                            event_id=event.event_id,
                        )
                    finally:
                        db2.close()
                except Exception:
                    pass
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
