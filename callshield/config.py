"""Persistent, validated configuration for CALLSHIELD.

Configuration is stored as JSON in the local data directory. Phase 5 retains
all Phase 1–4 settings and adds explicitly confirmed active-policy controls.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Optional

from . import DATA_DIR
from .intelligence.profiles import PROFILES, get_profile
from .utils import ConfigError, safe_write_text

CONFIG_PATH = DATA_DIR / "config.json"

# Phase 1 legacy modes mapped to Phase 2 profile names.
_LEGACY_MODE_MAP = {
    "PERMISSIVE": "RELAXED",
    "BALANCED": "BALANCED",
    "STRICT": "STRICT",
}
DEFAULT_PROFILE = "BALANCED"

# Friendly aliases accepted when upgrading hand-written configuration files.
# Values are persisted using the established repository names.
_CONFIG_ALIASES = {
    "daemon_pid_file": "pid_file",
    "daemon_socket": "socket_path",
    "queue_size": "event_queue_size",
    "watch_interval": "status_refresh_interval",
}


def _default_weights() -> Dict[str, int]:
    return dict(PROFILES["BALANCED"].signal_weights)


def _configured_data_dir() -> Path:
    return Path(os.environ.get("CALLSHIELD_DATA_DIR", str(DATA_DIR))).expanduser()


def _runtime_root() -> Path:
    """Return the private CALLSHIELD runtime root.

    Installed deployments set ``CALLSHIELD_DATA_DIR`` to ``~/.callshield/data``.
    For the older convention where the override itself was a generic state
    directory, retain the historical ``<override>/run`` behavior.
    """

    # An explicit data-directory override is the most specific runtime scope
    # (and is how tests/alternate installs isolate state).
    if os.environ.get("CALLSHIELD_DATA_DIR"):
        data_dir = _configured_data_dir()
        return data_dir.parent if data_dir.name == "data" else data_dir
    explicit_home = os.environ.get("CALLSHIELD_HOME")
    if explicit_home:
        return Path(explicit_home).expanduser()
    data_dir = _configured_data_dir()
    return data_dir.parent if data_dir.name == "data" else data_dir


def _configured_log_dir() -> Path:
    return Path(
        os.environ.get("CALLSHIELD_LOG_DIR", str(_runtime_root() / "logs"))
    ).expanduser()


@dataclass
class Config:
    """All persisted CALLSHIELD configuration values."""

    default_country: str = "IN"
    risk_threshold: int = PROFILES[DEFAULT_PROFILE].risk_threshold
    high_risk_threshold: int = PROFILES[DEFAULT_PROFILE].high_risk_threshold
    logging_enabled: bool = True
    color_enabled: str = "AUTO"  # AUTO | ON | OFF
    protection_mode: str = DEFAULT_PROFILE
    database_path: str = field(
        default_factory=lambda: str(_configured_data_dir() / "callshield.db")
    )
    # Phase 3 uses the private run directory. Existing config files which
    # explicitly contain the Phase 1 data-directory path remain supported.
    pid_file: str = field(
        default_factory=lambda: str(_runtime_root() / "run" / "callshield.pid")
    )
    log_file: str = field(
        default_factory=lambda: str(_configured_log_dir() / "callshield.log")
    )

    # Phase 2 additions.
    history_weight: float = 1.0
    report_weight: float = 1.0
    pattern_weight: float = 0.5
    signal_weights: Dict[str, int] = field(default_factory=_default_weights)
    recent_window_seconds: int = 600
    output_json: bool = False
    quiet: bool = False

    # Phase 3 additions: daemon, local IPC, and bounded resources only.
    daemon_enabled: bool = True
    heartbeat_interval: int = 30
    event_queue_size: int = 256
    shutdown_timeout: int = 10
    status_refresh_interval: int = 2
    ipc_timeout: float = 5.0
    event_payload_limit: int = 8 * 1024
    max_log_size: int = 2 * 1024 * 1024
    max_log_files: int = 3
    ipc_enabled: bool = True
    run_dir: str = field(default_factory=lambda: str(_runtime_root() / "run"))
    daemon_log_file: str = field(
        default_factory=lambda: str(_configured_log_dir() / "daemon.log")
    )
    socket_path: str = field(
        default_factory=lambda: str(_runtime_root() / "run" / "callshield.sock")
    )

    # Phase 4/5 screening controls. Fresh installs are disabled and DRY_RUN.
    screening_enabled: bool = False
    screening_mode: str = "DRY_RUN"
    screening_timeout_ms: int = 1500
    active_mode_confirmed: bool = False
    screening_policy: str = "BALANCED"
    relaxed_active_block_threshold: int = 92
    relaxed_confidence_threshold: int = 90
    balanced_active_block_threshold: int = 85
    balanced_confidence_threshold: int = 80
    strict_active_block_threshold: int = 80
    strict_confidence_threshold: int = 75
    emergency_off_file: str = field(
        default_factory=lambda: str(_runtime_root() / "state" / "emergency_off")
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        if not isinstance(data, dict):
            raise ConfigError("Configuration root must be a JSON object.")
        base = cls()
        valid = {f.name for f in fields(cls)}
        for raw_key, value in data.items():
            key = _CONFIG_ALIASES.get(raw_key, raw_key)
            if key not in valid:
                continue
            if key == "protection_mode" and isinstance(value, str):
                value = _LEGACY_MODE_MAP.get(value.upper(), value.upper())
            setattr(base, key, value)
        if base.protection_mode in _LEGACY_MODE_MAP:
            base.protection_mode = _LEGACY_MODE_MAP[base.protection_mode]

        # Activation state fails safe. An ACTIVE value without the separate
        # confirmation marker is downgraded and disabled during load, so an
        # upgrade can never silently activate blocking.
        if not isinstance(base.screening_enabled, bool):
            base.screening_enabled = False
        if not isinstance(base.active_mode_confirmed, bool):
            base.active_mode_confirmed = False
        if isinstance(base.screening_mode, str):
            base.screening_mode = base.screening_mode.upper().replace("-", "_")
        if base.screening_mode not in ("DRY_RUN", "ACTIVE"):
            base.screening_mode = "DRY_RUN"
            base.screening_enabled = False
            base.active_mode_confirmed = False
        if base.screening_mode == "ACTIVE" and not base.active_mode_confirmed:
            base.screening_mode = "DRY_RUN"
            base.screening_enabled = False
        if base.screening_mode == "DRY_RUN":
            base.active_mode_confirmed = False
        if isinstance(base.screening_policy, str):
            base.screening_policy = base.screening_policy.upper()
        if (
            isinstance(base.screening_timeout_ms, bool)
            or not isinstance(base.screening_timeout_ms, int)
            or not (200 <= base.screening_timeout_ms <= 5000)
        ):
            base.screening_timeout_ms = 1500

        base._apply_profile_defaults_if_needed()
        base._validate()
        return base

    def _apply_profile_defaults_if_needed(self) -> None:
        try:
            profile = get_profile(self.protection_mode)
        except KeyError:
            return
        if not self.signal_weights:
            self.signal_weights = dict(profile.signal_weights)
        if profile.name != DEFAULT_PROFILE:
            balanced = PROFILES["BALANCED"]
            if self.risk_threshold == balanced.risk_threshold:
                self.risk_threshold = profile.risk_threshold
            if self.high_risk_threshold == balanced.high_risk_threshold:
                self.high_risk_threshold = profile.high_risk_threshold

    def _validate(self) -> None:
        if self.protection_mode not in PROFILES:
            raise ConfigError(
                f"Invalid profile '{self.protection_mode}'. "
                f"Expected one of: {', '.join(sorted(PROFILES))}."
            )
        for name, val in (
            ("risk_threshold", self.risk_threshold),
            ("high_risk_threshold", self.high_risk_threshold),
        ):
            if isinstance(val, bool) or not isinstance(val, int) or not (0 <= val <= 100):
                raise ConfigError(f"{name} must be an integer between 0 and 100.")
        if self.color_enabled not in ("AUTO", "ON", "OFF"):
            raise ConfigError("color_enabled must be AUTO, ON or OFF.")
        if not isinstance(self.logging_enabled, bool):
            raise ConfigError("logging_enabled must be true or false.")
        if not isinstance(self.default_country, str) or not (1 <= len(self.default_country) <= 4):
            raise ConfigError("default_country must be a short ISO country code (e.g. IN, US).")
        for wname in ("history_weight", "report_weight", "pattern_weight"):
            value = getattr(self, wname)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not (0.0 <= float(value) <= 5.0):
                raise ConfigError(f"{wname} must be a number between 0 and 5.")
        if isinstance(self.recent_window_seconds, bool) or not isinstance(self.recent_window_seconds, int) or self.recent_window_seconds < 10:
            raise ConfigError("recent_window_seconds must be an integer >= 10.")
        if not isinstance(self.signal_weights, dict):
            raise ConfigError("signal_weights must be a mapping of signal name -> integer weight.")
        for key, value in self.signal_weights.items():
            if (
                not isinstance(key, str)
                or isinstance(value, bool)
                or not isinstance(value, int)
                or not (-100 <= value <= 100)
            ):
                raise ConfigError(
                    f"Invalid signal weight for '{key}': must be an integer between -100 and 100."
                )

        for name in (
            "daemon_enabled",
            "ipc_enabled",
            "screening_enabled",
            "active_mode_confirmed",
        ):
            if not isinstance(getattr(self, name), bool):
                raise ConfigError(f"{name} must be true or false.")
        if self.screening_mode not in ("DRY_RUN", "ACTIVE"):
            raise ConfigError("screening_mode must be DRY_RUN or ACTIVE.")
        if self.screening_mode == "ACTIVE" and not self.active_mode_confirmed:
            raise ConfigError("ACTIVE mode requires explicit confirmation.")
        if self.screening_mode == "DRY_RUN" and self.active_mode_confirmed:
            raise ConfigError("DRY_RUN cannot carry an active confirmation marker.")
        if self.screening_policy not in ("RELAXED", "BALANCED", "STRICT"):
            raise ConfigError("screening_policy must be RELAXED, BALANCED, or STRICT.")
        self._validate_int("screening_timeout_ms", 200, 5000)
        for threshold_name in (
            "relaxed_active_block_threshold",
            "relaxed_confidence_threshold",
            "balanced_active_block_threshold",
            "balanced_confidence_threshold",
            "strict_active_block_threshold",
            "strict_confidence_threshold",
        ):
            self._validate_int(threshold_name, 0, 100)
        self._validate_int("heartbeat_interval", 5, 600)
        self._validate_int("event_queue_size", 16, 2048)
        self._validate_int("shutdown_timeout", 1, 60)
        self._validate_int("status_refresh_interval", 1, 10)
        self._validate_int("event_payload_limit", 256, 8 * 1024)
        self._validate_int("max_log_size", 64 * 1024, 100 * 1024 * 1024)
        self._validate_int("max_log_files", 1, 10)
        if (
            isinstance(self.ipc_timeout, bool)
            or not isinstance(self.ipc_timeout, (int, float))
            or not (0.1 <= float(self.ipc_timeout) <= 30.0)
        ):
            raise ConfigError("ipc_timeout must be a number between 0.1 and 30 seconds.")

        for name in (
            "run_dir",
            "daemon_log_file",
            "socket_path",
            "pid_file",
            "database_path",
            "log_file",
            "emergency_off_file",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                raise ConfigError(f"{name} must be a non-empty filesystem path.")
        # Linux/Termux Unix-domain paths are commonly limited to 107 bytes.
        if len(os.fsencode(os.path.expanduser(self.socket_path))) > 100:
            raise ConfigError("socket_path is too long for a portable Unix domain socket (max 100 bytes).")

    def _validate_int(self, name: str, minimum: int, maximum: int) -> None:
        value = getattr(self, name)
        if isinstance(value, bool) or not isinstance(value, int) or not (minimum <= value <= maximum):
            raise ConfigError(f"{name} must be an integer between {minimum} and {maximum}.")


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration, creating a private default file when absent."""

    target = Path(path) if path is not None else Path(CONFIG_PATH)
    if not target.exists():
        cfg = Config()
        save_config(cfg, target)
        return cfg
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Unable to read config file {target}: {exc}") from exc
    return Config.from_dict(data)


def save_config(cfg: Config, path: Optional[Path] = None) -> None:
    """Persist configuration atomically with owner-only permissions."""

    target = Path(path) if path is not None else Path(CONFIG_PATH)
    cfg._validate()
    safe_write_text(target, json.dumps(cfg.to_dict(), indent=2, sort_keys=True) + "\n")


def set_profile(cfg: Config, profile: str) -> Config:
    key = profile.upper()
    if key not in PROFILES:
        raise ConfigError(
            f"Unknown profile '{profile}'. Available: {', '.join(sorted(PROFILES))}."
        )
    selected = PROFILES[key]
    cfg.protection_mode = selected.name
    cfg.risk_threshold = selected.risk_threshold
    cfg.high_risk_threshold = selected.high_risk_threshold
    cfg.signal_weights = dict(selected.signal_weights)
    return cfg


# Backwards-compatible alias (Phase 1 called it "mode").
def set_mode(cfg: Config, mode: str) -> Config:
    return set_profile(cfg, mode)


def set_value(cfg: Config, key: str, value: str) -> Config:
    """Set one value from the CLI with strict type coercion and validation."""

    key = key.lower().replace("-", "_")
    key = _CONFIG_ALIASES.get(key, key)
    bool_true = {"1", "true", "on", "yes"}
    bool_false = {"0", "false", "off", "no"}

    if key in {"profile", "protection_mode", "mode"}:
        if value.upper() == "PERMISSIVE":
            value = "RELAXED"
        return set_profile(cfg, value)
    if key == "screening_mode":
        normalized_mode = value.upper().replace("-", "_")
        if normalized_mode != "DRY_RUN":
            raise ConfigError(
                "ACTIVE mode can only be enabled by `callshield screening mode active` confirmation."
            )
        cfg.screening_mode = "DRY_RUN"
        cfg.active_mode_confirmed = False
        cfg._validate()
        return cfg
    if key == "screening_policy":
        normalized_policy = value.upper()
        if normalized_policy not in ("RELAXED", "BALANCED", "STRICT"):
            raise ConfigError("screening_policy must be RELAXED, BALANCED, or STRICT.")
        cfg.screening_policy = normalized_policy
        cfg._validate()
        return cfg
    if key == "screening_enabled" and value.lower() in bool_true:
        if cfg.screening_mode == "ACTIVE":
            raise ConfigError(
                "Use `callshield screening mode active` to confirm active protection."
            )
    if not hasattr(cfg, key):
        raise ConfigError(f"Unknown configuration key: {key}")

    path_fields = {
        "default_country",
        "color_enabled",
        "database_path",
        "pid_file",
        "log_file",
        "run_dir",
        "daemon_log_file",
        "socket_path",
        "emergency_off_file",
    }
    int_fields = {
        "risk_threshold",
        "high_risk_threshold",
        "recent_window_seconds",
        "heartbeat_interval",
        "event_queue_size",
        "shutdown_timeout",
        "status_refresh_interval",
        "event_payload_limit",
        "screening_timeout_ms",
        "relaxed_active_block_threshold",
        "relaxed_confidence_threshold",
        "balanced_active_block_threshold",
        "balanced_confidence_threshold",
        "strict_active_block_threshold",
        "strict_confidence_threshold",
        "max_log_size",
        "max_log_files",
    }
    bool_fields = {
        "logging_enabled",
        "output_json",
        "quiet",
        "daemon_enabled",
        "ipc_enabled",
        "screening_enabled",
    }

    if key in path_fields:
        setattr(cfg, key, value.upper() if key == "color_enabled" else value)
    elif key in int_fields:
        try:
            text = value.strip().upper()
            if key == "max_log_size" and text.endswith("MB"):
                integer = int(float(text[:-2].strip()) * 1024 * 1024)
            elif key == "max_log_size" and text.endswith("KB"):
                integer = int(float(text[:-2].strip()) * 1024)
            else:
                integer = int(value)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{key} must be an integer.") from exc
        setattr(cfg, key, integer)
    elif key in bool_fields:
        normalized = value.lower()
        if normalized in bool_true:
            setattr(cfg, key, True)
        elif normalized in bool_false:
            setattr(cfg, key, False)
        else:
            raise ConfigError(f"{key} must be true or false.")
    elif key in {"history_weight", "report_weight", "pattern_weight", "ipc_timeout"}:
        try:
            setattr(cfg, key, float(value))
        except ValueError as exc:
            raise ConfigError(f"{key} must be a number.") from exc
    elif key == "signal_weights":
        try:
            pairs = [part.strip() for part in value.split(",") if part.strip()]
            weights = dict(cfg.signal_weights)
            for pair in pairs:
                if "=" not in pair:
                    raise ConfigError(
                        f"signal_weights entries must be name=value (got '{pair}')"
                    )
                name, raw_weight = pair.split("=", 1)
                weights[name.strip()] = int(raw_weight.strip())
            cfg.signal_weights = weights
        except ValueError as exc:
            raise ConfigError(f"Invalid signal_weights format: {exc}") from exc
    else:
        raise ConfigError(f"Setting '{key}' is not directly configurable via CLI.")
    cfg._validate()
    return cfg
