"""Safe PID and Unix-socket runtime management for CALLSHIELD Phase 3."""

from __future__ import annotations

import errno
import os
import signal
import socket
import stat
import time
from pathlib import Path
from typing import List, Optional, Tuple

from ..config import Config, load_config
from ..utils import CallShieldError


class DaemonError(CallShieldError):
    """Expected daemon lifecycle failure."""


def _run_dir(cfg: Config) -> Path:
    path = Path(cfg.run_dir).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def _pid_path(cfg: Config) -> Path:
    return Path(cfg.pid_file).expanduser()


def _all_pid_paths(cfg: Config) -> List[Path]:
    """Known CALLSHIELD PID locations, canonical first.

    The extra locations are only Phase 1/early-Phase-3 compatibility paths.
    No path outside configured CALLSHIELD data/run directories is inferred.
    """

    candidates = [
        _pid_path(cfg),
        Path(cfg.run_dir).expanduser() / "callshield.pid",
        Path(cfg.database_path).expanduser().parent / "callshield.pid",
    ]
    result = []  # type: List[Path]
    for candidate in candidates:
        if candidate not in result:
            result.append(candidate)
    return result


def _socket_path(cfg: Config) -> Path:
    return Path(cfg.socket_path).expanduser()


def _is_owned_regular_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    getuid = getattr(os, "geteuid", None)
    return getuid is None or info.st_uid == getuid()


def _read_pid_from(path: Path) -> Optional[int]:
    if not _is_owned_regular_file(path):
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip().split()
        if not raw:
            return None
        pid = int(raw[0])
        return pid if pid > 1 else None
    except (OSError, UnicodeError, ValueError):
        return None


def _pid_record(cfg: Config) -> Tuple[Optional[Path], Optional[int]]:
    for path in _all_pid_paths(cfg):
        try:
            exists = path.exists() or path.is_symlink()
        except OSError:
            exists = False
        if exists:
            return path, _read_pid_from(path)
    return None, None


def _read_pid(cfg: Config) -> Optional[int]:
    return _pid_record(cfg)[1]


def _pid_alive(pid: int) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists, but inability to inspect/signal is never treated as ours.
        return True
    except OSError as exc:
        return exc.errno != errno.ESRCH
    return True


def _proc_cmdline(pid: int) -> Optional[List[str]]:
    """Read Linux/Termux process arguments without invoking a shell."""

    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return [
        part.decode("utf-8", errors="replace")
        for part in raw.split(b"\x00")
        if part
    ]


def _pid_is_callshield(pid: int) -> bool:
    """Return true only for CALLSHIELD's exact foreground daemon command.

    Merely being a Python process is deliberately insufficient: accepting any
    Python PID could terminate an unrelated application. On platforms without
    safe process inspection, ownership remains unverified and no signal is sent.
    """

    args = _proc_cmdline(pid)
    if not args or "_run-fg" not in args:
        return False
    for index, value in enumerate(args[:-1]):
        if value == "-m" and args[index + 1] == "callshield":
            return True
    return False


def _process_identity(pid: int) -> Optional[str]:
    """Return Linux process start time, used to detect PID reuse."""

    try:
        # /proc/<pid>/stat field 22 is starttime. The command field may contain
        # spaces/parentheses, so split only after its final closing parenthesis.
        content = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        remainder = content[content.rfind(")") + 2 :].split()
        return remainder[19]  # field 22 after removing pid/comm
    except (OSError, IndexError, ValueError):
        return None


def _safe_unlink_pid(path: Path, expected_pid: Optional[int] = None) -> bool:
    if not _is_owned_regular_file(path):
        return False
    if expected_pid is not None and _read_pid_from(path) != expected_pid:
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def _write_pid(cfg: Config) -> int:
    """Atomically claim the PID file for the current process."""

    path = _pid_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass

    # Clean only known, owner-owned stale PID files. A verified live daemon is
    # always preserved and causes duplicate startup rejection.
    for candidate in _all_pid_paths(cfg):
        if not (candidate.exists() or candidate.is_symlink()):
            continue
        if not _is_owned_regular_file(candidate):
            raise DaemonError(
                f"Unsafe PID path is not an owner-owned regular file: {candidate}"
            )
        existing = _read_pid_from(candidate)
        if existing and _pid_alive(existing) and (
            existing == os.getpid() or _pid_is_callshield(existing)
        ):
            raise DaemonError(
                f"CALLSHIELD engine is already running (PID {existing})."
            )
        _safe_unlink_pid(candidate, expected_pid=existing)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        raise DaemonError("CALLSHIELD PID file was claimed by another startup.") from exc
    try:
        pid = os.getpid()
        os.write(descriptor, f"{pid}\n".encode("ascii"))
        try:
            os.fsync(descriptor)
        except OSError:
            pass
    finally:
        os.close(descriptor)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return pid


def _clear_pid(cfg: Config, expected_pid: Optional[int] = None) -> None:
    """Remove only owner-owned PID files matching ``expected_pid``."""

    for path in _all_pid_paths(cfg):
        _safe_unlink_pid(path, expected_pid=expected_pid)


def _is_owned_socket(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    if not stat.S_ISSOCK(info.st_mode):
        return False
    getuid = getattr(os, "geteuid", None)
    return getuid is None or info.st_uid == getuid()


def _socket_is_active(cfg: Config, timeout: float = 0.2) -> bool:
    path = _socket_path(cfg)
    if not _is_owned_socket(path):
        return False
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(timeout)
        client.connect(str(path))
        return True
    except (ConnectionRefusedError, FileNotFoundError, socket.timeout):
        return False
    except OSError:
        # Permission and unexpected errors are treated as active/unsafe: never
        # unlink an endpoint we could not prove stale.
        return True
    finally:
        client.close()


def _clear_socket(cfg: Config) -> bool:
    """Remove only a stale, owner-owned Unix socket at the configured path."""

    path = _socket_path(cfg)
    if not _is_owned_socket(path) or _socket_is_active(cfg):
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def status(cfg: Optional[Config] = None) -> Tuple[str, Optional[int]]:
    """Return ``(RUNNING|STOPPED|STALE, pid)`` without modifying state."""

    selected = cfg or load_config()
    path, pid = _pid_record(selected)
    if path is None:
        return "STOPPED", None
    if pid is None:
        return "STALE", None
    if not _pid_alive(pid):
        return "STALE", pid
    if not _pid_is_callshield(pid):
        return "STALE", pid
    return "RUNNING", pid


def start(cfg: Optional[Config] = None) -> int:
    """Claim daemon runtime state in the current process.

    The user-facing CLI launches ``_run-fg``; this function remains as the
    compatible low-level Phase 1/2 API and is also useful in lifecycle tests.
    """

    selected = cfg or load_config()
    state, pid = status(selected)
    if state == "RUNNING":
        raise DaemonError(f"CALLSHIELD engine is already running (PID {pid}).")
    if state == "STALE":
        _clear_pid(selected, expected_pid=pid)
        _clear_socket(selected)
    return _write_pid(selected)


def stop(
    cfg: Optional[Config] = None, timeout: Optional[float] = None
) -> Tuple[bool, Optional[int]]:
    """Gracefully stop a verified CALLSHIELD daemon.

    An unrelated or unverifiable process is never signalled. PID identity is
    checked again before the optional final kill to protect against PID reuse.
    """

    selected = cfg or load_config()
    if timeout is None:
        timeout = float(selected.shutdown_timeout)
    path, pid = _pid_record(selected)
    if path is None:
        return False, None
    if pid is None:
        _clear_pid(selected)
        _clear_socket(selected)
        return True, None
    if not _pid_alive(pid):
        _clear_pid(selected, expected_pid=pid)
        _clear_socket(selected)
        return True, pid
    if not _pid_is_callshield(pid):
        # The PID file is CALLSHIELD state and may be cleaned, but the unrelated
        # live process is intentionally untouched.
        _clear_pid(selected, expected_pid=pid)
        _clear_socket(selected)
        return False, pid

    identity = _process_identity(pid)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _clear_pid(selected, expected_pid=pid)
        _clear_socket(selected)
        return True, pid
    except PermissionError as exc:
        raise DaemonError(f"Cannot signal CALLSHIELD PID {pid}: {exc}") from exc

    deadline = time.monotonic() + max(0.0, float(timeout))
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            _clear_pid(selected, expected_pid=pid)
            _clear_socket(selected)
            return True, pid
        time.sleep(0.1)

    # A wedged daemon may require a final signal. Re-verify both command and
    # process start time immediately before doing so; otherwise leave it alone.
    if (
        identity is not None
        and _pid_is_callshield(pid)
        and _process_identity(pid) == identity
    ):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise DaemonError(f"Cannot terminate CALLSHIELD PID {pid}: {exc}") from exc
        final_deadline = time.monotonic() + 1.0
        while time.monotonic() < final_deadline and _pid_alive(pid):
            time.sleep(0.05)

    if _pid_alive(pid):
        raise DaemonError(
            f"CALLSHIELD PID {pid} did not stop; runtime files were preserved."
        )
    _clear_pid(selected, expected_pid=pid)
    _clear_socket(selected)
    return True, pid
