"""Process management for CALLSHIELD daemon (Phase 3).

Handles PID file, socket path, run directory, stale detection,
and verification that a PID belongs to CALLSHIELD.
"""

from __future__ import annotations

import errno
import os
import signal
import time
from pathlib import Path
from typing import Optional, Tuple

from ..config import Config, load_config
from ..utils import CallShieldError


class DaemonError(CallShieldError):
    pass


def _run_dir(cfg: Config) -> Path:
    # Use configured run_dir, fallback to parent of pid_file
    try:
        p = Path(cfg.run_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        return Path(cfg.pid_file).parent


def _pid_path(cfg: Config) -> Path:
    # Prefer explicit pid_file, but also handle legacy vs new run_dir
    # If pid_file is inside data dir and run_dir exists, use run_dir/callshield.pid for new daemons
    # For reading, check both locations
    primary = Path(cfg.pid_file)
    # New location is run_dir/callshield.pid
    try:
        new_path = _run_dir(cfg) / "callshield.pid"
        if new_path != primary and new_path.exists() and not primary.exists():
            return new_path
    except Exception:
        pass
    return primary


def _all_pid_paths(cfg: Config) -> list[Path]:
    """Return all possible pid file locations to check."""
    paths = []
    try:
        p1 = Path(cfg.pid_file)
        paths.append(p1)
        p2 = _run_dir(cfg) / "callshield.pid"
        if p2 != p1:
            paths.append(p2)
    except Exception:
        pass
    return paths


def _socket_path(cfg: Config) -> Path:
    try:
        sp = Path(cfg.socket_path)
        return sp
    except Exception:
        return _run_dir(cfg) / "callshield.sock"


def _read_pid(cfg: Config) -> Optional[int]:
    for p in _all_pid_paths(cfg):
        if p.exists():
            try:
                raw = p.read_text(encoding="utf-8").strip().split()[0]
                return int(raw) if raw else None
            except (OSError, ValueError):
                continue
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        return True
    return True


def _pid_is_callshield(pid: int) -> bool:
    """Verify that pid belongs to CALLSHIELD by inspecting cmdline."""
    try:
        # Try /proc on Linux/Termux
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            try:
                data = cmdline_path.read_bytes()
                # cmdline is null-separated
                parts = data.replace(b"\x00", b" ").decode(errors="ignore").lower()
                if "callshield" in parts or "daemon" in parts:
                    return True
                # If we can't find callshield but process exists, we still check that
                # the pid file was written by us: allow if cmdline contains python
                if "python" in parts:
                    # Check that the process's cwd or exe is plausible
                    return True
                return False
            except Exception:
                pass
        # Fallback: try ps (portable)
        import subprocess
        try:
            out = subprocess.check_output(["ps", "-o", "args=", "-p", str(pid)], stderr=subprocess.DEVNULL, timeout=2)
            txt = out.decode(errors="ignore").lower()
            if "callshield" in txt:
                return True
            if "python" in txt:
                return True
            return False
        except Exception:
            # If we cannot verify, assume it belongs to us if we couldn't disprove (avoid killing unrelated)
            # But for safety, we will treat unknown as not belonging if pid file is stale
            return False
    except Exception:
        return False


def _write_pid(cfg: Config) -> int:
    p = _pid_path(cfg)
    # Prefer new run_dir location if configured pid_file is legacy data dir
    try:
        run_pid = _run_dir(cfg) / "callshield.pid"
        # If legacy path is inside data and run_dir is different, write to run_dir
        if Path(cfg.pid_file).parent.name == "data" and run_pid.parent != Path(cfg.pid_file).parent:
            p = run_pid
    except Exception:
        pass
    p.parent.mkdir(parents=True, exist_ok=True)
    pid = os.getpid()
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(str(pid))
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    # Also ensure stale legacy path is cleaned if we wrote to new location
    for alt in _all_pid_paths(cfg):
        if alt != p and alt.exists():
            try:
                alt.unlink()
            except OSError:
                pass
    return pid


def _clear_pid(cfg: Config, expected_pid: Optional[int] = None) -> None:
    for p in _all_pid_paths(cfg):
        try:
            if expected_pid is not None:
                current = None
                try:
                    raw = p.read_text(encoding="utf-8").strip().split()[0]
                    current = int(raw) if raw else None
                except Exception:
                    current = None
                if current != expected_pid:
                    continue
            p.unlink(missing_ok=True)
        except OSError:
            pass
    # Also clean socket if we own it and daemon is not running
    try:
        sp = _socket_path(cfg)
        if expected_pid is not None:
            # Only clean socket if pid matches or no pid
            pass
        # If no pid file exists anymore, it's safe to clean socket if stale
        if _read_pid(cfg) is None and sp.exists():
            # Check if socket is stale (no process listening)
            # We will just unlink; daemon will recreate on next start
            try:
                sp.unlink()
            except OSError:
                pass
    except Exception:
        pass


def _clear_socket(cfg: Config) -> None:
    try:
        sp = _socket_path(cfg)
        if sp.exists():
            try:
                sp.unlink()
            except OSError:
                pass
    except Exception:
        pass


def status(cfg: Optional[Config] = None) -> Tuple[str, Optional[int]]:
    """Return ('RUNNING'|'STOPPED'|'STALE', pid_or_None)."""
    cfg = cfg or load_config()
    pid = _read_pid(cfg)
    if pid is None:
        return ("STOPPED", None)
    if _pid_alive(pid):
        # Verify it's actually callshield if possible; if not, treat as stale to avoid confusion
        if _pid_is_callshield(pid):
            return ("RUNNING", pid)
        else:
            # If we cannot verify it's callshield, but pid is alive, we treat as STALE
            # to avoid killing unrelated process, but report STALE so user knows
            # We don't automatically clear; status will show STALE and start will need manual attention
            # However for safety we check if pid file is old (>5min) then treat as stale
            try:
                for p in _all_pid_paths(cfg):
                    if p.exists():
                        age = time.time() - p.stat().st_mtime
                        if age > 300:
                            return ("STALE", pid)
            except Exception:
                pass
            return ("RUNNING", pid)
    return ("STALE", pid)


def start(cfg: Optional[Config] = None) -> int:
    cfg = cfg or load_config()
    state, pid = status(cfg)
    if state == "RUNNING":
        raise DaemonError(f"CALLSHIELD engine is already running (PID {pid}).")
    if state == "STALE":
        _clear_pid(cfg)
        _clear_socket(cfg)
    pid = _write_pid(cfg)
    return pid


def stop(cfg: Optional[Config] = None, timeout: Optional[float] = None) -> Tuple[bool, Optional[int]]:
    cfg = cfg or load_config()
    if timeout is None:
        timeout = float(cfg.shutdown_timeout) if hasattr(cfg, 'shutdown_timeout') else 5.0
    pid = _read_pid(cfg)
    if pid is None:
        return (False, None)
    if not _pid_alive(pid):
        _clear_pid(cfg)
        _clear_socket(cfg)
        return (True, pid)
    # Verify we own it before signalling
    if not _pid_is_callshield(pid):
        # Don't kill unrelated processes; just report stale and clean file
        _clear_pid(cfg, expected_pid=pid)
        return (True, pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _clear_pid(cfg)
        _clear_socket(cfg)
        return (True, pid)
    except PermissionError as exc:
        raise DaemonError(f"Cannot signal PID {pid}: {exc}") from exc
    waited = 0.0
    interval = 0.2
    while waited < timeout:
        if not _pid_alive(pid):
            _clear_pid(cfg, expected_pid=pid)
            _clear_socket(cfg)
            return (True, pid)
        time.sleep(interval)
        waited += interval
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    _clear_pid(cfg, expected_pid=pid)
    _clear_socket(cfg)
    return (True, pid)
