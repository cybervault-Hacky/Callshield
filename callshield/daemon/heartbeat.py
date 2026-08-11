"""Lightweight heartbeat for the persistent Phase 3 daemon."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from ..config import Config
from ..database import Database
from ..utils import safe_write_text


class Heartbeat:
    """Periodically records liveness in local state and SQLite."""

    def __init__(
        self,
        cfg: Config,
        interval: Optional[float] = None,
        on_beat: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.cfg = cfg
        selected = float(cfg.heartbeat_interval) if interval is None else float(interval)
        if selected <= 0:
            raise ValueError("heartbeat interval must be positive")
        self.interval = selected
        self.on_beat = on_beat
        self.last_beat = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None  # type: Optional[threading.Thread]

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        # Beat synchronously so status is meaningful as soon as startup returns.
        self.beat()
        self._thread = threading.Thread(
            target=self._run, name="callshield-heartbeat", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)

    def update_interval(self, interval: float) -> None:
        selected = float(interval)
        if selected <= 0:
            raise ValueError("heartbeat interval must be positive")
        with self._lock:
            self.interval = selected

    def beat(self) -> None:
        """Perform one bounded best-effort liveness update."""

        now = time.time()
        with self._lock:
            self.last_beat = now
        try:
            run_dir = Path(self.cfg.run_dir).expanduser()
            run_dir.mkdir(parents=True, exist_ok=True)
            try:
                run_dir.chmod(0o700)
            except OSError:
                pass
            state_file = run_dir / "heartbeat.json"
            data = {
                "timestamp": now,
                "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "pid": os.getpid(),
            }
            safe_write_text(state_file, json.dumps(data, sort_keys=True) + "\n")
        except Exception:
            # Health reporting must remain alive even on a read-only filesystem.
            pass

        database = None
        try:
            database = Database(self.cfg.database_path)
            database.set_setting("heartbeat", str(int(now)))
            database.set_setting(
                "heartbeat_iso",
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            )
        except Exception:
            pass
        finally:
            if database is not None:
                try:
                    database.close()
                except Exception:
                    pass
        if self.on_beat:
            try:
                self.on_beat(now)
            except Exception:
                pass

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                age = time.time() - self.last_beat
                interval = self.interval
            if age >= interval:
                try:
                    self.beat()
                except Exception:
                    pass
            # A one-second maximum sleep keeps shutdown/reload responsive while
            # remaining effectively idle between the default 30-second beats.
            self._stop.wait(timeout=min(1.0, max(0.1, interval)))

    def is_fresh(self, max_age: Optional[float] = None) -> bool:
        with self._lock:
            last_beat = self.last_beat
            interval = self.interval
        if last_beat <= 0:
            return False
        allowed_age = interval * 2 + 10 if max_age is None else float(max_age)
        return (time.time() - last_beat) <= allowed_age
