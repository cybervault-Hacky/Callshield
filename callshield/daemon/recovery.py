"""Crash-safe runtime validation and recovery for CALLSHIELD Phase 3."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Optional

from ..config import Config, load_config
from ..database import Database
from .process import (
    DaemonError,
    _clear_pid,
    _clear_socket,
    _is_owned_socket,
    _socket_is_active,
    _socket_path,
    status,
)


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir():
        raise RuntimeError(f"Runtime path is not a directory: {path}")
    try:
        path.chmod(0o700)
    except OSError:
        pass


def validate_startup(cfg: Optional[Config] = None) -> Config:
    """Validate configuration, database, and private runtime directories."""

    selected = cfg or load_config()
    try:
        selected._validate()
    except Exception as exc:
        raise RuntimeError(f"Configuration invalid: {exc}") from exc
    if not selected.daemon_enabled:
        raise RuntimeError("Daemon is disabled by configuration (daemon_enabled=false).")

    database = None
    try:
        database = Database(selected.database_path)
        database.get_setting("heartbeat")
    except Exception as exc:
        raise RuntimeError(
            f"Database unavailable at {selected.database_path}: {exc}"
        ) from exc
    finally:
        if database is not None:
            try:
                database.close()
            except Exception:
                pass

    try:
        run_dir = Path(selected.run_dir).expanduser()
        log_dir = Path(selected.daemon_log_file).expanduser().parent
        state_dir = run_dir.parent / "state"
        for directory in (run_dir, log_dir, state_dir):
            _secure_directory(directory)
    except Exception as exc:
        raise RuntimeError(f"Cannot prepare private runtime directories: {exc}") from exc

    if selected.ipc_enabled:
        socket_path = _socket_path(selected)
        try:
            _secure_directory(socket_path.parent)
        except Exception as exc:
            raise RuntimeError(
                f"IPC endpoint directory is unavailable for {socket_path}: {exc}"
            ) from exc
        if socket_path.exists() or socket_path.is_symlink():
            try:
                mode = socket_path.lstat().st_mode
            except OSError as exc:
                raise RuntimeError(f"Cannot inspect IPC endpoint {socket_path}: {exc}") from exc
            if not stat.S_ISSOCK(mode):
                raise RuntimeError(
                    f"Refusing to replace non-socket runtime path: {socket_path}"
                )
    return selected


def recover_runtime(cfg: Config) -> None:
    """Recover only known stale CALLSHIELD PID/socket artifacts.

    Active sockets, non-socket files, symlinks, and unowned endpoints are never
    removed. An unrelated process referenced by a stale PID file is not
    signalled.
    """

    state, pid = status(cfg)
    if state == "RUNNING":
        raise DaemonError(f"CALLSHIELD engine is already running (PID {pid}).")
    if state == "STALE":
        _clear_pid(cfg, expected_pid=pid)

    socket_path = _socket_path(cfg)
    if not (socket_path.exists() or socket_path.is_symlink()):
        return
    if not _is_owned_socket(socket_path):
        raise RuntimeError(
            f"Refusing to remove unowned or non-socket runtime path: {socket_path}"
        )
    if _socket_is_active(cfg, timeout=min(0.5, float(cfg.ipc_timeout))):
        raise DaemonError(
            f"An active Unix socket already exists at {socket_path}; startup aborted."
        )
    if not _clear_socket(cfg):
        raise RuntimeError(f"Unable to remove stale Unix socket: {socket_path}")


def handle_event_exception(
    event_id: str, exc: Exception, logger: Optional[logging.Logger] = None
) -> None:
    """Record a per-event failure without propagating it to the daemon loop."""

    if logger:
        try:
            logger.exception("Event %s failed: %s", event_id, exc)
        except Exception:
            pass
