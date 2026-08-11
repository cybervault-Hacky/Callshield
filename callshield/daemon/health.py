"""Thread-safe health and metrics monitoring through CALLSHIELD Phase 5."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import Config
from ..database import Database


class HealthMonitor:
    """In-memory daemon health tracker whose failures never escape callers."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.start_time = time.time()
        self.pid = os.getpid()
        self.state = "STARTING"
        self.queue_size = 0
        self.queue_max = int(cfg.event_queue_size)
        self.processed = 0
        self.failed = 0
        self.received = 0
        self.dropped = 0
        self.queue_peak = 0
        self.high_risk_count = 0
        self.blocked_recommendations = 0
        self.analysis_count = 0
        # Screening/policy counters. Actual rejection is separate from a
        # daemon-applied block and increments only after Android feedback.
        self.incoming_calls = 0
        self.screened = 0
        self.screening_timeouts = 0
        self.bridge_errors = 0
        self.policy_errors = 0
        self.screening_high_risk = 0
        self.screening_allowed = 0
        self.screening_unknown = 0
        self.screening_block_recommended = 0
        self.screening_blocked = 0
        self.actually_rejected = 0
        self.last_screening = None  # type: Optional[str]
        self.last_event = None  # type: Optional[str]
        self.last_heartbeat = None  # type: Optional[float]
        self.last_error = None  # type: Optional[str]
        self.db_status = "UNKNOWN"
        self._lock = threading.Lock()

    def set_state(self, state: str) -> None:
        with self._lock:
            self.state = str(state)

    def update_config(self, cfg: Config) -> None:
        with self._lock:
            self.cfg = cfg
            # Queue capacity cannot change without restart; retain queue_max.

    def update_queue(self, size: int, peak: Optional[int] = None) -> None:
        with self._lock:
            self.queue_size = max(0, int(size))
            if peak is not None:
                self.queue_peak = max(self.queue_peak, int(peak))

    def inc_received(self) -> None:
        with self._lock:
            self.received += 1

    def inc_processed(
        self, verdict: Optional[str] = None, action: Optional[str] = None
    ) -> None:
        with self._lock:
            self.processed += 1
            self.analysis_count += 1
            self.last_event = _utc_text()
            if verdict in ("HIGH_RISK", "MALICIOUS"):
                self.high_risk_count += 1
            if action == "BLOCK":
                self.blocked_recommendations += 1

    def inc_failed(self, error: Optional[str] = None) -> None:
        with self._lock:
            self.failed += 1
            self.last_event = _utc_text()
            if error:
                self.last_error = str(error)[:512]

    def inc_dropped(self) -> None:
        with self._lock:
            self.dropped += 1

    def inc_incoming_call(self) -> None:
        with self._lock:
            self.incoming_calls += 1
            self.last_screening = _utc_text()

    def record_screening(
        self,
        *,
        verdict: str,
        recommended_action: str,
        applied_action: str,
        reason: str,
        bridge_error: bool = False,
        policy_error: bool = False,
    ) -> None:
        """Record one screening response without implying device rejection."""

        with self._lock:
            self.screened += 1
            self.last_screening = _utc_text()
            if applied_action == "BLOCK":
                self.screening_blocked += 1
            else:
                self.screening_allowed += 1
            if reason == "SCREENING_TIMEOUT":
                self.screening_timeouts += 1
            if bridge_error:
                self.bridge_errors += 1
            if policy_error:
                self.policy_errors += 1
            if verdict in ("HIGH_RISK", "MALICIOUS"):
                self.screening_high_risk += 1
            if verdict == "UNKNOWN":
                self.screening_unknown += 1
            if recommended_action == "BLOCK":
                self.screening_block_recommended += 1

    def confirm_actual_rejection(self) -> None:
        with self._lock:
            self.actually_rejected += 1

    def inc_bridge_error(self) -> None:
        with self._lock:
            self.bridge_errors += 1

    # Compatibility aliases retained for historical Phase 4 consumers.
    def inc_screening(self) -> None:
        self.inc_incoming_call()

    def inc_screening_processed(self) -> None:
        with self._lock:
            self.screened += 1
            self.screening_allowed += 1

    def inc_screening_timeout(self) -> None:
        with self._lock:
            self.screening_timeouts += 1

    def set_heartbeat(self, timestamp: Optional[float] = None) -> None:
        with self._lock:
            self.last_heartbeat = time.time() if timestamp is None else float(timestamp)

    def check_db(self) -> str:
        database = None
        try:
            database = Database(self.cfg.database_path)
            database.get_setting("heartbeat")
            status = "ONLINE"
        except Exception:
            status = "ERROR"
        finally:
            if database is not None:
                try:
                    database.close()
                except Exception:
                    pass
        with self._lock:
            self.db_status = status
        return status

    def _get_memory(self) -> Optional[int]:
        try:
            status_path = Path(f"/proc/{self.pid}/status")
            if status_path.exists():
                for line in status_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1])
        except Exception:
            pass
        try:
            import resource

            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if rss > 1024 * 1024:  # macOS reports bytes; Linux reports KiB.
                rss //= 1024
            return int(rss)
        except Exception:
            return None

    def snapshot(self) -> Dict[str, Any]:
        """Return a complete health snapshot; never raise."""

        try:
            with self._lock:
                values = {
                    "state": self.state,
                    "pid": self.pid,
                    "queue_size": self.queue_size,
                    "queue_max": self.queue_max,
                    "queue_peak": self.queue_peak,
                    "processed": self.processed,
                    "failed": self.failed,
                    "received": self.received,
                    "dropped": self.dropped,
                    "analysis_count": self.analysis_count,
                    "high_risk_count": self.high_risk_count,
                    "blocked_recommendations": self.blocked_recommendations,
                    "incoming_calls": self.incoming_calls,
                    "screened": self.screened,
                    "screening_timeouts": self.screening_timeouts,
                    "bridge_errors": self.bridge_errors,
                    "policy_errors": self.policy_errors,
                    "screening_high_risk": self.screening_high_risk,
                    "screening_allowed": self.screening_allowed,
                    "screening_unknown": self.screening_unknown,
                    "screening_block_recommended": self.screening_block_recommended,
                    "screening_blocked": self.screening_blocked,
                    "actually_rejected": self.actually_rejected,
                    "last_screening": self.last_screening,
                    "last_event": self.last_event,
                    "last_heartbeat": self.last_heartbeat,
                    "last_error": self.last_error,
                    "db_status": self.db_status,
                    "start_time": self.start_time,
                    "heartbeat_interval": float(self.cfg.heartbeat_interval),
                }
            now = time.time()
            uptime = max(0.0, now - float(values.pop("start_time")))
            heartbeat = values.get("last_heartbeat")
            age = None if heartbeat is None else max(0.0, now - float(heartbeat))
            stale_after = float(values.pop("heartbeat_interval")) * 3.0
            values.update(
                {
                    "uptime_seconds": int(uptime),
                    "uptime_human": self._format_uptime(uptime),
                    "last_heartbeat_human": (
                        time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(heartbeat))
                        )
                        if heartbeat is not None
                        else None
                    ),
                    "heartbeat_age_seconds": int(age) if age is not None else None,
                    "heartbeat_stale": age is None or age > stale_after,
                    "memory_kb": self._get_memory(),
                }
            )
            # Stable aliases make IPC consumers independent of display names.
            values["events_received"] = values["received"]
            values["events_processed"] = values["processed"]
            values["events_failed"] = values["failed"]
            values["events_dropped"] = values["dropped"]
            return values
        except Exception as exc:
            return {
                "state": "DEGRADED",
                "pid": os.getpid(),
                "uptime_seconds": 0,
                "uptime_human": "00:00:00",
                "queue_size": 0,
                "queue_max": int(getattr(self.cfg, "event_queue_size", 256)),
                "queue_peak": 0,
                "processed": 0,
                "failed": 0,
                "received": 0,
                "dropped": 0,
                "incoming_calls": 0,
                "screened": 0,
                "screening_timeouts": 0,
                "bridge_errors": 0,
                "policy_errors": 0,
                "screening_high_risk": 0,
                "screening_allowed": 0,
                "screening_unknown": 0,
                "screening_block_recommended": 0,
                "screening_blocked": 0,
                "actually_rejected": 0,
                "last_error": f"health snapshot unavailable: {exc}",
                "db_status": "UNKNOWN",
                "heartbeat_stale": True,
                "memory_kb": None,
            }

    @staticmethod
    def _format_uptime(seconds: float) -> str:
        total = max(0, int(seconds))
        hours = total // 3600
        minutes = (total % 3600) // 60
        remaining = total % 60
        return f"{hours:02d}:{minutes:02d}:{remaining:02d}"

    def is_healthy(self) -> bool:
        try:
            snapshot = self.snapshot()
            if snapshot.get("db_status") == "ERROR":
                return False
            if snapshot.get("last_heartbeat") is not None and snapshot.get(
                "heartbeat_stale"
            ):
                return False
            maximum = max(1, int(snapshot.get("queue_max", 1)))
            if int(snapshot.get("queue_size", 0)) > maximum * 0.9:
                return False
            return snapshot.get("state") not in ("STOPPING", "STOPPED", "DEGRADED")
        except Exception:
            return False


def _utc_text() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
