"""Health monitoring for CALLSHIELD daemon (Phase 3).

Tracks daemon state, uptime, PID, queue size, processed/failed, last event,
heartbeat, DB status, memory usage.
"""

from __future__ import annotations

import os
import time
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import Config
from ..database import Database


class HealthMonitor:
    """In-memory health tracker with thread-safe updates."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.start_time: float = time.time()
        self.pid: int = os.getpid()
        self.state: str = "STARTING"  # STARTING, RUNNING, STOPPING, STOPPED
        self.queue_size: int = 0
        self.queue_max: int = int(cfg.event_queue_size)
        self.processed: int = 0
        self.failed: int = 0
        self.received: int = 0
        self.dropped: int = 0
        self.queue_peak: int = 0
        self.high_risk_count: int = 0
        self.blocked_recommendations: int = 0
        self.analysis_count: int = 0
        # Phase 4 screening metrics
        self.screening_received: int = 0
        self.screening_processed: int = 0
        self.screening_timeouts: int = 0
        self.bridge_errors: int = 0
        self.last_screening: Optional[str] = None
        self.last_event: Optional[str] = None
        self.last_heartbeat: Optional[float] = None
        self.last_error: Optional[str] = None
        self.db_status: str = "UNKNOWN"
        self.memory_kb: Optional[int] = None
        self._lock = threading.Lock()

    def set_state(self, state: str) -> None:
        with self._lock:
            self.state = state

    def update_queue(self, size: int, peak: Optional[int] = None) -> None:
        with self._lock:
            self.queue_size = size
            if peak is not None and peak > self.queue_peak:
                self.queue_peak = peak

    def inc_received(self) -> None:
        with self._lock:
            self.received += 1

    def inc_processed(self, verdict: Optional[str] = None, action: Optional[str] = None) -> None:
        with self._lock:
            self.processed += 1
            self.analysis_count += 1
            self.last_event = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if verdict in ("HIGH_RISK", "MALICIOUS"):
                self.high_risk_count += 1
            if action == "BLOCK":
                self.blocked_recommendations += 1

    def inc_failed(self, error: Optional[str] = None) -> None:
        with self._lock:
            self.failed += 1
            if error:
                self.last_error = error

    def inc_dropped(self) -> None:
        with self._lock:
            self.dropped += 1

    def inc_screening(self) -> None:
        with self._lock:
            self.screening_received += 1
            self.last_screening = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def inc_screening_processed(self) -> None:
        with self._lock:
            self.screening_processed += 1

    def inc_screening_timeout(self) -> None:
        with self._lock:
            self.screening_timeouts += 1

    def inc_bridge_error(self) -> None:
        with self._lock:
            self.bridge_errors += 1

    def set_heartbeat(self) -> None:
        with self._lock:
            self.last_heartbeat = time.time()

    def check_db(self) -> str:
        try:
            db = Database(self.cfg.database_path)
            db.get_setting("heartbeat")
            db.close()
            status = "ONLINE"
        except Exception:
            status = "ERROR"
        with self._lock:
            self.db_status = status
        return status

    def _get_memory(self) -> Optional[int]:
        try:
            # Try /proc/self/status
            p = Path(f"/proc/{self.pid}/status")
            if p.exists():
                for line in p.read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        parts = line.split()
                        if len(parts) >= 2:
                            return int(parts[1])  # kB
        except Exception:
            pass
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # On Linux ru_maxrss is KB, on macOS bytes
            if rss > 1024*1024:
                rss = rss // 1024
            return int(rss)
        except Exception:
            return None

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            uptime = time.time() - self.start_time
            db_status = self.db_status
            mem = self._get_memory()
            # Also try to get queue metrics if available
            return {
                "state": self.state,
                "pid": self.pid,
                "uptime_seconds": int(uptime),
                "uptime_human": self._format_uptime(uptime),
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
                "screening_received": self.screening_received,
                "screening_processed": self.screening_processed,
                "screening_timeouts": self.screening_timeouts,
                "bridge_errors": self.bridge_errors,
                "last_screening": self.last_screening,
                "last_event": self.last_event,
                "last_heartbeat": self.last_heartbeat,
                "last_heartbeat_human": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.last_heartbeat)) if self.last_heartbeat else None,
                "db_status": db_status,
                "memory_kb": mem,
            }

    def _format_uptime(self, seconds: float) -> str:
        secs = int(seconds)
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def is_healthy(self) -> bool:
        snap = self.snapshot()
        # Healthy if DB online, heartbeat recent, queue not saturated
        if snap["db_status"] == "ERROR":
            return False
        if snap["last_heartbeat"]:
            age = time.time() - snap["last_heartbeat"]
            if age > (self.cfg.heartbeat_interval * 3):
                return False
        if snap["queue_size"] > snap["queue_max"] * 0.9:
            return False
        return True
