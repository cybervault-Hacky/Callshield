"""Background engine foundation for CALLSHIELD.

In Phase 1 the daemon is intentionally minimal: it maintains process state via
a PID file, writes periodic heartbeats, verifies the database is reachable,
and shuts down cleanly on SIGTERM/SIGINT. It does NOT access any telephony APIs
and does NOT intercept live calls — that is reserved for later phases.
"""

from __future__ import annotations

import errno
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

from . import __version__
from .config import Config, load_config
from .database import Database
from .logger import log_error, log_info
from .utils import CallShieldError


HEARTBEAT_INTERVAL_SECONDS = 30


class DaemonError(CallShieldError):
    pass


def _pid_path(cfg: Config) -> Path:
    return Path(cfg.pid_file)


def _read_pid(cfg: Config) -> Optional[int]:
    p = _pid_path(cfg)
    if not p.exists():
        return None
    try:
        raw = p.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it; treat as alive.
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        return True
    return True


def _clear_pid(cfg: Config, expected_pid: Optional[int] = None) -> None:
    p = _pid_path(cfg)
    try:
        if expected_pid is not None:
            current = _read_pid(cfg)
            if current != expected_pid:
                return
        p.unlink(missing_ok=True)
    except OSError:
        pass


def _write_pid(cfg: Config) -> int:
    p = _pid_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(str(pid))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return pid


def status(cfg: Optional[Config] = None) -> Tuple[str, Optional[int]]:
    """Return ('RUNNING'|'STOPPED'|'STALE', pid_or_None)."""
    cfg = cfg or load_config()
    pid = _read_pid(cfg)
    if pid is None:
        return ("STOPPED", None)
    if _pid_alive(pid):
        return ("RUNNING", pid)
    return ("STALE", pid)


def start(cfg: Optional[Config] = None) -> int:
    """Start the background engine. Returns the daemon PID.

    Note: Phase 1 daemon is a cooperative in-process background loop.
    For true Unix daemonization (double-fork) use the ``--foreground``-free
    path via CLI; here we expose a ``run_foreground`` loop that the CLI
    backgrounds via subprocess in Phase 1 to keep the code simple and portable
    across Termux where setsid is available but double-forking complicates PID
    tracking.
    """
    cfg = cfg or load_config()
    state, pid = status(cfg)
    if state == "RUNNING":
        raise DaemonError(f"CALLSHIELD engine is already running (PID {pid}).")
    if state == "STALE":
        _clear_pid(cfg)
    # In the Phase 1 CLI we spawn this process via `subprocess.Popen` with
    # `start-process` flag; write PID and run the loop.
    pid = _write_pid(cfg)
    return pid


def stop(cfg: Optional[Config] = None, timeout: float = 5.0) -> Tuple[bool, Optional[int]]:
    """Stop the running engine. Returns (stopped?, pid)."""
    cfg = cfg or load_config()
    pid = _read_pid(cfg)
    if pid is None:
        return (False, None)
    if not _pid_alive(pid):
        _clear_pid(cfg)
        return (True, pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _clear_pid(cfg)
        return (True, pid)
    except PermissionError as exc:
        raise DaemonError(f"Cannot signal PID {pid}: {exc}") from exc
    # Wait up to timeout for graceful exit.
    waited = 0.0
    while waited < timeout:
        if not _pid_alive(pid):
            _clear_pid(cfg, expected_pid=pid)
            return (True, pid)
        time.sleep(0.2)
        waited += 0.2
    # Force kill.
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    _clear_pid(cfg, expected_pid=pid)
    return (True, pid)


def run_foreground(cfg: Optional[Config] = None) -> int:
    """Run the engine event loop in the foreground.

    Used by the CLI when it spawns a background subprocess. Exits on SIGTERM
    or SIGINT.
    """
    cfg = cfg or load_config()
    pid = os.getpid()
    _write_pid(cfg)
    log_info(cfg, f"CALLSHIELD v{__version__} engine starting (pid={pid}, mode=STANDBY)")

    _shutdown = {"flag": False}

    def _handle_signal(signum, _frame):
        log_info(cfg, f"Received signal {signum}; shutting down")
        _shutdown["flag"] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # Verify DB once at startup
    try:
        db = Database(cfg.database_path)
        db.get_setting("heartbeat")
        db.close()
    except Exception as exc:  # noqa: BLE001
        log_error(cfg, f"Database check failed: {exc}")

    last = 0.0
    try:
        while not _shutdown["flag"]:
            now = time.time()
            if now - last >= HEARTBEAT_INTERVAL_SECONDS:
                try:
                    db = Database(cfg.database_path)
                    db.set_setting("heartbeat", str(int(now)))
                    db.set_setting("engine_pid", str(pid))
                    db.set_setting("engine_mode", "STANDBY")
                    db.close()
                    log_info(cfg, "heartbeat ok")
                except Exception as exc:  # noqa: BLE001
                    log_error(cfg, f"heartbeat failed: {exc}")
                last = now
            time.sleep(0.5)
    finally:
        _clear_pid(cfg, expected_pid=pid)
        log_info(cfg, "engine stopped")
    return 0
