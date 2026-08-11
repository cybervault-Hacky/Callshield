"""Phase 6 read-mostly diagnostics and narrowly scoped safe repairs."""

from __future__ import annotations

import os
import platform
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config as config_module
from .adaptive import BehaviorStorage
from .config import Config, config_integrity
from .daemon.process import _clear_pid, _clear_socket, status as daemon_status
from .database import Database, SCHEMA_VERSION
from .policy import is_emergency_off, thresholds_for_config
from .reputation import ReputationStorage
from .utils import safe_unlink


HEALTHY = "HEALTHY"
WARNING = "WARNING"
ERROR = "ERROR"
NOT_VERIFIED = "NOT VERIFIED"


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str
    repaired: bool = False


@dataclass
class DoctorReport:
    checks: List[DoctorCheck]

    @property
    def status(self) -> str:
        statuses = {check.status for check in self.checks}
        if ERROR in statuses:
            return ERROR
        if WARNING in statuses:
            return WARNING
        return HEALTHY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "checks": [asdict(check) for check in self.checks],
        }


def run_doctor(
    cfg: Config,
    *,
    repair: bool = False,
    ipc_request: Optional[
        Callable[[Config, Dict[str, Any]], Optional[Dict[str, Any]]]
    ] = None,
) -> DoctorReport:
    checks = []  # type: List[DoctorCheck]
    checks.append(
        DoctorCheck(
            "Runtime",
            HEALTHY,
            f"{platform.system()} {platform.release()} ({platform.machine()})",
        )
    )
    python_ok = sys.version_info >= (3, 8)
    checks.append(
        DoctorCheck(
            "Python",
            HEALTHY if python_ok else ERROR,
            platform.python_version(),
        )
    )

    config_path = Path(config_module.CONFIG_PATH)
    config_error = config_integrity(config_path)
    repaired_config_mode = False
    if repair and config_path.exists() and _owned_regular(config_path):
        try:
            config_path.chmod(0o600)
            repaired_config_mode = True
            _remove_abandoned_config_temps(config_path)
        except OSError:
            pass
    checks.append(
        DoctorCheck(
            "Config",
            ERROR if config_error else HEALTHY,
            config_error or f"valid, mode {oct(_mode(config_path))}",
            repaired_config_mode,
        )
    )

    database = None
    try:
        database = Database(cfg.database_path, timeout=1.0)
        database.integrity_check()
        database.validate_schema()
        checks.append(
            DoctorCheck(
                "Database",
                HEALTHY,
                f"integrity ok, schema {SCHEMA_VERSION}, WAL, foreign keys on",
            )
        )
        checks.append(DoctorCheck("Schema", HEALTHY, f"version {SCHEMA_VERSION}"))
        reputation_storage = ReputationStorage(database, cfg)
        reputation_ok = reputation_storage.integrity_check()
        profile_count = int(
            database._conn.execute(
                "SELECT COUNT(*) FROM reputation_profiles"
            ).fetchone()[0]
        )
        trust_count = int(
            database._conn.execute(
                "SELECT COUNT(*) FROM trusted_numbers"
            ).fetchone()[0]
        )
        checks.append(
            DoctorCheck(
                "Reputation Database",
                HEALTHY,
                f"local profiles={profile_count}",
            )
        )
        checks.append(
            DoctorCheck("Reputation Schema", HEALTHY, "schema and indexes present")
        )
        checks.append(
            DoctorCheck(
                "Reputation Integrity",
                HEALTHY if reputation_ok else ERROR,
                "bounded profile JSON valid" if reputation_ok else "corrupt profile JSON",
            )
        )
        checks.append(
            DoctorCheck("Trust Database", HEALTHY, f"local trust records={trust_count}")
        )
        behavior_storage = BehaviorStorage(database, cfg)
        intelligence_ok = behavior_storage.integrity_check()
        observation_count = int(
            database._conn.execute(
                "SELECT COUNT(*) FROM intelligence_observations"
            ).fetchone()[0]
        )
        intelligence_profile_count = int(
            database._conn.execute(
                "SELECT COUNT(*) FROM intelligence_profiles"
            ).fetchone()[0]
        )
        checks.append(
            DoctorCheck(
                "Intelligence Database",
                HEALTHY,
                f"observations={observation_count} profiles={intelligence_profile_count}",
            )
        )
        checks.append(
            DoctorCheck("Intelligence Schema", HEALTHY, "schema and indexes present")
        )
        checks.append(
            DoctorCheck(
                "Intelligence Integrity",
                HEALTHY if intelligence_ok else ERROR,
                "bounded derived JSON valid" if intelligence_ok else "corrupt intelligence JSON",
            )
        )
        checks.append(
            DoctorCheck(
                "Intelligence Storage",
                HEALTHY,
                "hashes and masked identifiers only",
            )
        )
        checks.append(
            DoctorCheck(
                "Intelligence Retention",
                HEALTHY,
                (
                    f"observations={cfg.intelligence_observation_limit} "
                    f"profiles={cfg.intelligence_profile_limit} "
                    f"age={cfg.intelligence_history_days}d"
                ),
            )
        )
    except Exception as exc:
        checks.append(DoctorCheck("Database", ERROR, str(exc)))
        checks.append(DoctorCheck("Schema", ERROR, "not validated"))
        checks.append(DoctorCheck("Reputation Database", ERROR, "not available"))
        checks.append(DoctorCheck("Reputation Schema", ERROR, "not validated"))
        checks.append(DoctorCheck("Reputation Integrity", ERROR, "not validated"))
        checks.append(DoctorCheck("Trust Database", ERROR, "not available"))
        checks.append(DoctorCheck("Intelligence Database", ERROR, "not available"))
        checks.append(DoctorCheck("Intelligence Schema", ERROR, "not validated"))
        checks.append(DoctorCheck("Intelligence Integrity", ERROR, "not validated"))
        checks.append(DoctorCheck("Intelligence Storage", ERROR, "not available"))
        checks.append(DoctorCheck("Intelligence Retention", ERROR, "not validated"))
    finally:
        if database is not None:
            try:
                database.close()
            except Exception:
                pass

    state, pid = daemon_status(cfg)
    repaired_runtime = False
    if repair and state == "STALE":
        _clear_pid(cfg, expected_pid=pid)
        _clear_socket(cfg)
        state, pid = daemon_status(cfg)
        repaired_runtime = True
    elif repair and state == "STOPPED":
        repaired_runtime = _clear_socket(cfg) or repaired_runtime
    checks.append(
        DoctorCheck(
            "Daemon",
            HEALTHY if state == "RUNNING" else WARNING,
            f"{state}" + (f" pid={pid}" if pid else ""),
            repaired_runtime,
        )
    )

    if state == "RUNNING" and ipc_request is not None:
        response = ipc_request(cfg, {"command": "ping"})
        ipc_ok = bool(
            response
            and response.get("status") == "ok"
            and response.get("pong") is True
        )
        checks.append(
            DoctorCheck(
                "IPC",
                HEALTHY if ipc_ok else ERROR,
                "owner-only Unix socket responded" if ipc_ok else "daemon IPC unavailable",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "IPC",
                WARNING,
                "not checked while daemon is stopped"
                if state != "RUNNING"
                else "no IPC diagnostic callback",
            )
        )

    permission_repairs = _check_permissions(cfg, repair=repair)
    permission_errors = [item for item in permission_repairs if not item[1]]
    checks.append(
        DoctorCheck(
            "Permissions",
            ERROR if permission_errors else HEALTHY,
            "; ".join(item[0] for item in permission_repairs)
            if permission_repairs
            else "runtime paths absent or restrictive",
            any(item[2] for item in permission_repairs),
        )
    )

    bridge_path = (
        Path(__file__).resolve().parent.parent
        / "android/app/src/main/java/com/callshield/bridge/BridgeClient.kt"
    )
    checks.append(
        DoctorCheck(
            "Android Bridge",
            NOT_VERIFIED,
            "source present; build/device not verified"
            if bridge_path.exists()
            else "source missing",
        )
    )
    try:
        thresholds = thresholds_for_config(cfg)
        policy_detail = (
            f"{cfg.screening_policy} active={thresholds.active_block} "
            f"confidence={thresholds.confidence}"
        )
        policy_status = HEALTHY
    except Exception as exc:
        policy_detail = f"invalid, fail-open: {exc}"
        policy_status = ERROR
    checks.append(DoctorCheck("Policy", policy_status, policy_detail))
    checks.append(
        DoctorCheck(
            "Screening",
            HEALTHY if not cfg.screening_enabled or policy_status == HEALTHY else ERROR,
            f"enabled={cfg.screening_enabled} mode={cfg.screening_mode} "
            f"emergency_off={is_emergency_off(cfg)}",
        )
    )

    try:
        statvfs = os.statvfs(str(Path(cfg.database_path).parent))
        free_bytes = int(statvfs.f_bavail * statvfs.f_frsize)
        storage_status = HEALTHY if free_bytes >= 10 * 1024 * 1024 else WARNING
        storage_detail = f"{free_bytes} bytes free"
    except OSError as exc:
        storage_status = WARNING
        storage_detail = f"unavailable: {exc}"
    checks.append(DoctorCheck("Storage", storage_status, storage_detail))
    return DoctorReport(checks)


def _check_permissions(cfg: Config, *, repair: bool) -> List[tuple]:
    paths = [
        (Path(cfg.run_dir), 0o700),
        (Path(cfg.database_path).parent, 0o700),
        (Path(cfg.daemon_log_file).parent, 0o700),
        (Path(cfg.run_dir).parent / "state", 0o700),
        (Path(config_module.CONFIG_PATH), 0o600),
        (Path(cfg.database_path), 0o600),
        (Path(cfg.emergency_off_file), 0o600),
        (Path(cfg.socket_path), 0o600),
    ]
    results = []
    for path, expected in paths:
        if not (path.exists() or path.is_symlink()):
            continue
        try:
            info = path.lstat()
            owned = not hasattr(os, "geteuid") or info.st_uid == os.geteuid()
            safe_type = stat.S_ISDIR(info.st_mode) if expected == 0o700 else (
                stat.S_ISREG(info.st_mode) or stat.S_ISSOCK(info.st_mode)
            )
            repaired = False
            if repair and owned and safe_type and (info.st_mode & 0o777) != expected:
                path.chmod(expected)
                repaired = True
                info = path.lstat()
            ok = owned and safe_type and (info.st_mode & 0o777) == expected
            results.append((f"{path}: {oct(info.st_mode & 0o777)}", ok, repaired))
        except OSError as exc:
            results.append((f"{path}: {exc}", False, False))
    return results


def _remove_abandoned_config_temps(config_path: Path) -> None:
    pattern = f".{config_path.name}.*.tmp"
    for candidate in config_path.parent.glob(pattern):
        if _owned_regular(candidate):
            try:
                safe_unlink(candidate)
            except OSError:
                pass


def _owned_regular(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and (
        not hasattr(os, "geteuid") or info.st_uid == os.geteuid()
    )


def _mode(path: Path) -> int:
    try:
        return path.lstat().st_mode & 0o777
    except OSError:
        return 0
