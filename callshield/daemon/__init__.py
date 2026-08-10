"""Daemon package for CALLSHIELD Phase 3.

Re-exports legacy daemon API for backward compatibility (Phase 1/2)
and exposes new service components.
"""

from __future__ import annotations

from .process import DaemonError, status, start, stop, _clear_pid, _read_pid, _write_pid, _pid_alive
from .service import DaemonService, run_foreground
from .health import HealthMonitor
from .heartbeat import Heartbeat

# Keep old constants for compatibility
HEARTBEAT_INTERVAL_SECONDS = 30

__all__ = [
    "DaemonError",
    "DaemonService",
    "HealthMonitor",
    "Heartbeat",
    "HEARTBEAT_INTERVAL_SECONDS",
    "status",
    "start",
    "stop",
    "run_foreground",
    "_clear_pid",
    "_read_pid",
    "_write_pid",
    "_pid_alive",
]
