"""Crash recovery for CALLSHIELD daemon (Phase 3).

Handles per-event exceptions without killing the daemon,
and validates startup prerequisites.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from ..config import Config, load_config
from ..database import Database
from ..utils import ConfigError, DatabaseError


def validate_startup(cfg: Optional[Config] = None) -> Config:
    """Validate configuration, database, runtime directories, IPC endpoint.

    Returns validated cfg or raises with useful error.
    """
    if cfg is None:
        try:
            cfg = load_config()
        except ConfigError as exc:
            raise RuntimeError(f"Configuration invalid: {exc}") from exc

    # 1. validate configuration (already done in load_config)
    # 2. validate database
    try:
        db = Database(cfg.database_path)
        db.get_setting("heartbeat")
        db.close()
    except Exception as exc:
        raise RuntimeError(f"Database unavailable at {cfg.database_path}: {exc}") from exc

    # 3. runtime directory
    try:
        run_dir = Path(cfg.run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        run_dir.chmod(0o700)
    except Exception as exc:
        raise RuntimeError(f"Cannot create run directory {cfg.run_dir}: {exc}") from exc

    # 4. log directory
    try:
        log_dir = Path(cfg.daemon_log_file).parent
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        raise RuntimeError(f"Cannot create log directory for {cfg.daemon_log_file}: {exc}") from exc

    # 5. IPC endpoint - check if socket path is writable
    if cfg.ipc_enabled:
        try:
            sp = Path(cfg.socket_path)
            sp.parent.mkdir(parents=True, exist_ok=True)
            # If socket exists and is stale, it will be cleaned on start
        except Exception as exc:
            raise RuntimeError(f"IPC endpoint invalid {cfg.socket_path}: {exc}") from exc

    # 6. duplicate daemon check is done by caller (process.status)
    # 7-10 are runtime (queue, workers, heartbeat, mark RUNNING) handled by service

    return cfg


def handle_event_exception(event_id: str, exc: Exception, logger: Optional[logging.Logger] = None) -> None:
    """Log per-event failure without crashing daemon."""
    if logger:
        logger.exception(f"Event {event_id} failed: {exc}")
    # Caller should increment failure metric and continue
