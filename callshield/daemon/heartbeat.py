"""Heartbeat for CALLSHIELD daemon (Phase 3).

Lightweight periodic heartbeat that updates state without heavy DB writes.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from ..config import Config
from ..database import Database


class Heartbeat:
    """Manages periodic heartbeat updates."""

    def __init__(self, cfg: Config, interval: Optional[int] = None) -> None:
        self.cfg = cfg
        self.interval = interval or int(cfg.heartbeat_interval)
        self.last_beat: float = 0.0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="callshield-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def beat(self) -> None:
        """Perform a single heartbeat update."""
        now = time.time()
        # Lightweight: write to DB but also to state file
        try:
            # Ensure run/state directories exist
            run_dir = Path(self.cfg.run_dir)
            run_dir.mkdir(parents=True, exist_ok=True)
            state_file = run_dir / "heartbeat.json"
            # Write lightweight JSON
            import json
            data = {
                "timestamp": now,
                "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "pid": __import__("os").getpid(),
            }
            # Use safe write
            from ..utils import safe_write_text
            safe_write_text(state_file, json.dumps(data) + "\n")
        except Exception:
            pass
        try:
            db = Database(self.cfg.database_path)
            db.set_setting("heartbeat", str(int(now)))
            db.set_setting("heartbeat_iso", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)))
            db.close()
        except Exception:
            pass
        self.last_beat = now

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                if time.time() - self.last_beat >= self.interval:
                    self.beat()
            except Exception:
                pass
            # Wait with timeout to allow quick shutdown
            self._stop.wait(timeout=1.0)

    def is_fresh(self, max_age: Optional[int] = None) -> bool:
        if max_age is None:
            max_age = self.interval * 2 + 10
        return (time.time() - self.last_beat) < max_age
