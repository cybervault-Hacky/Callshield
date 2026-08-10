"""Unix signal handling for CALLSHIELD daemon (Phase 3)."""

from __future__ import annotations

import signal
import threading
from typing import Callable, Optional

from ..config import Config


class SignalHandler:
    """Handles SIGTERM, SIGINT, SIGHUP for graceful shutdown/reload."""

    def __init__(self, cfg: Config, shutdown_cb: Callable[[], None], reload_cb: Optional[Callable[[], None]] = None) -> None:
        self.cfg = cfg
        self.shutdown_cb = shutdown_cb
        self.reload_cb = reload_cb
        self._shutdown_initiated = threading.Event()

    def install(self) -> None:
        try:
            signal.signal(signal.SIGTERM, self._handle_sigterm)
            signal.signal(signal.SIGINT, self._handle_sigint)
            # SIGHUP may not be available on all platforms, but try
            try:
                signal.signal(signal.SIGHUP, self._handle_sighup)
            except (ValueError, OSError):
                pass
        except Exception:
            pass

    def _handle_sigterm(self, signum, frame) -> None:
        self._shutdown_initiated.set()
        try:
            self.shutdown_cb()
        except Exception:
            pass

    def _handle_sigint(self, signum, frame) -> None:
        self._shutdown_initiated.set()
        try:
            self.shutdown_cb()
        except Exception:
            pass

    def _handle_sighup(self, signum, frame) -> None:
        if self.reload_cb:
            try:
                self.reload_cb()
            except Exception:
                pass

    def is_shutdown(self) -> bool:
        return self._shutdown_initiated.is_set()
