"""Persistent configuration for CALLSHIELD.

Configuration is stored in a JSON file inside the data directory. All settings
have safe defaults that work out of the box; the file is created on first run.
Phase 2 adds profiles, tunable signal weights, and extra thresholds while
remaining fully backward-compatible with Phase 1 configuration files.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict

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


def _default_weights() -> Dict[str, int]:
    # Deep copy from BALANCED profile to avoid shared mutable defaults.
    return dict(PROFILES["BALANCED"].signal_weights)


@dataclass
class Config:
    """All persisted configuration values."""

    default_country: str = "IN"
    risk_threshold: int = PROFILES[DEFAULT_PROFILE].risk_threshold
    high_risk_threshold: int = PROFILES[DEFAULT_PROFILE].high_risk_threshold
    logging_enabled: bool = True
    color_enabled: str = "AUTO"  # AUTO | ON | OFF
    protection_mode: str = DEFAULT_PROFILE  # now called "profile" but name kept for compat
    database_path: str = field(default_factory=lambda: str(DATA_DIR / "callshield.db"))
    pid_file: str = field(default_factory=lambda: str(DATA_DIR / "callshield.pid"))
    log_file: str = field(default_factory=lambda: str(DATA_DIR.parent / "logs" / "callshield.log"))
    # Phase 2 additions
    history_weight: float = 1.0
    report_weight: float = 1.0
    pattern_weight: float = 0.5
    signal_weights: Dict[str, int] = field(default_factory=_default_weights)
    recent_window_seconds: int = 600  # 10 minutes for "rapid repeat" detection
    output_json: bool = False
    quiet: bool = False
    # Phase 3 additions — daemon / IPC / resource control
    daemon_enabled: bool = True
    heartbeat_interval: int = 30
    event_queue_size: int = 256
    shutdown_timeout: int = 10
    status_refresh_interval: int = 2
    max_log_size: int = 2 * 1024 * 1024  # 2MB
    max_log_files: int = 3
    ipc_enabled: bool = True
    run_dir: str = field(default_factory=lambda: str(Path(os.environ.get("CALLSHIELD_DATA_DIR", str(DATA_DIR))).parent / "run" if Path(os.environ.get("CALLSHIELD_DATA_DIR", str(DATA_DIR))).name == "data" else str(Path(os.environ.get("CALLSHIELD_DATA_DIR", str(DATA_DIR))) / "run")))
    daemon_log_file: str = field(default_factory=lambda: str(Path(os.environ.get("CALLSHIELD_LOG_DIR", str(DATA_DIR.parent / "logs"))) / "daemon.log"))
    socket_path: str = field(default_factory=lambda: str(Path(os.environ.get("CALLSHIELD_DATA_DIR", str(DATA_DIR))).parent / "run" / "callshield.sock" if Path(os.environ.get("CALLSHIELD_DATA_DIR", str(DATA_DIR))).name == "data" else str(Path(os.environ.get("CALLSHIELD_DATA_DIR", str(DATA_DIR))) / "run" / "callshield.sock")))
    # Phase 4 additions — Android screening bridge
    screening_enabled: bool = True
    screening_mode: str = "DRY_RUN"  # DRY_RUN (Phase 4) or ACTIVE (Phase 5)
    screening_timeout_ms: int = 1500

    # ----- serialisation -----
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Config":
        base = cls()
        valid = {f.name for f in fields(cls)}
        for key, value in (data or {}).items():
            if key not in valid:
                continue
            # Accept legacy "mode" alias.
            if key == "protection_mode" and isinstance(value, str):
                value = _LEGACY_MODE_MAP.get(value.upper(), value.upper())
            setattr(base, key, value)
        # If the loaded mode is a Phase 1 legacy name, translate it.
        if base.protection_mode in _LEGACY_MODE_MAP:
            base.protection_mode = _LEGACY_MODE_MAP[base.protection_mode]
        # Normalize screening_mode
        if hasattr(base, "screening_mode") and isinstance(base.screening_mode, str):
            base.screening_mode = base.screening_mode.upper()
            if base.screening_mode not in ("DRY_RUN", "ACTIVE"):
                base.screening_mode = "DRY_RUN"
        base._apply_profile_defaults_if_needed()
        base._validate()
        return base

    def _apply_profile_defaults_if_needed(self) -> None:
        """If profile is valid but thresholds/weights weren't set, fill from profile."""
        try:
            profile = get_profile(self.protection_mode)
        except KeyError:
            return
        # Only override thresholds if they're at their dataclass defaults and
        # the user didn't provide custom weights. Compare against sentinel:
        # if signal_weights is empty/None, fill from profile.
        if not self.signal_weights:
            self.signal_weights = dict(profile.signal_weights)
        # Apply default thresholds from profile if they still match the
        # BALANCED defaults AND the profile isn't BALANCED.
        if profile.name != DEFAULT_PROFILE:
            # Respect explicit user-set values by leaving them alone *if* they
            # differ from all profile defaults; but to keep things simple and
            # predictable for Phase 2 we always reset thresholds from the
            # profile when they match BALANCED defaults.
            balanced = PROFILES["BALANCED"]
            if self.risk_threshold == balanced.risk_threshold:
                self.risk_threshold = profile.risk_threshold
            if self.high_risk_threshold == balanced.high_risk_threshold:
                self.high_risk_threshold = profile.high_risk_threshold

    # ----- validation -----
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
            if not isinstance(val, int) or not (0 <= val <= 100):
                raise ConfigError(f"{name} must be an integer between 0 and 100.")
        if self.color_enabled not in ("AUTO", "ON", "OFF"):
            raise ConfigError("color_enabled must be AUTO, ON or OFF.")
        if not isinstance(self.logging_enabled, bool):
            raise ConfigError("logging_enabled must be true or false.")
        if not isinstance(self.default_country, str) or len(self.default_country) > 4:
            raise ConfigError("default_country must be a short ISO country code (e.g. IN, US).")
        for wname in ("history_weight", "report_weight", "pattern_weight"):
            w = getattr(self, wname)
            if not isinstance(w, (int, float)) or not (0.0 <= float(w) <= 5.0):
                raise ConfigError(f"{wname} must be a number between 0 and 5.")
        if not isinstance(self.recent_window_seconds, int) or self.recent_window_seconds < 10:
            raise ConfigError("recent_window_seconds must be an integer >= 10.")
        if not isinstance(self.signal_weights, dict):
            raise ConfigError("signal_weights must be a mapping of signal name -> integer weight.")
        for k, v in self.signal_weights.items():
            if not isinstance(k, str) or not isinstance(v, int) or not (-100 <= v <= 100):
                raise ConfigError(
                    f"Invalid signal weight for '{k}': must be an integer between -100 and 100."
                )
        # Phase 3 validations
        for bname in ("daemon_enabled", "ipc_enabled"):
            if not isinstance(getattr(self, bname), bool):
                raise ConfigError(f"{bname} must be true or false.")
        if not isinstance(self.heartbeat_interval, int) or not (5 <= self.heartbeat_interval <= 600):
            raise ConfigError("heartbeat_interval must be an integer between 5 and 600.")
        if not isinstance(self.event_queue_size, int) or not (16 <= self.event_queue_size <= 2048):
            raise ConfigError("event_queue_size must be an integer between 16 and 2048.")
        if not isinstance(self.shutdown_timeout, int) or not (1 <= self.shutdown_timeout <= 60):
            raise ConfigError("shutdown_timeout must be an integer between 1 and 60.")
        if not isinstance(self.status_refresh_interval, int) or not (1 <= self.status_refresh_interval <= 10):
            raise ConfigError("status_refresh_interval must be an integer between 1 and 10.")
        if not isinstance(self.max_log_size, int) or not (64*1024 <= self.max_log_size <= 100*1024*1024):
            raise ConfigError("max_log_size must be an integer between 64KB and 100MB.")
        if not isinstance(self.max_log_files, int) or not (1 <= self.max_log_files <= 10):
            raise ConfigError("max_log_files must be an integer between 1 and 10.")
        for pname in ("run_dir", "daemon_log_file", "socket_path", "pid_file", "database_path", "log_file"):
            v = getattr(self, pname)
            if not isinstance(v, str) or not v.strip():
                raise ConfigError(f"{pname} must be a non-empty string path.")
        # Phase 4 validations
        if not isinstance(self.screening_enabled, bool):
            raise ConfigError("screening_enabled must be true or false.")
        if self.screening_mode not in ("DRY_RUN", "ACTIVE"):
            raise ConfigError("screening_mode must be DRY_RUN or ACTIVE.")
        if not isinstance(self.screening_timeout_ms, int) or not (200 <= self.screening_timeout_ms <= 5000):
            raise ConfigError("screening_timeout_ms must be an integer between 200 and 5000.")


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config from disk, returning defaults if missing."""
    if not path.exists():
        cfg = Config()
        save_config(cfg, path)
        return cfg
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Unable to read config file {path}: {exc}") from exc
    return Config.from_dict(data)


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    """Persist ``cfg`` to disk with restricted permissions."""
    cfg._validate()
    safe_write_text(path, json.dumps(cfg.to_dict(), indent=2, sort_keys=True) + "\n")


def set_profile(cfg: Config, profile: str) -> Config:
    """Apply a protection profile, resetting thresholds and weights to its defaults."""
    key = profile.upper()
    if key not in PROFILES:
        raise ConfigError(
            f"Unknown profile '{profile}'. Available: {', '.join(sorted(PROFILES))}."
        )
    p = PROFILES[key]
    cfg.protection_mode = p.name
    cfg.risk_threshold = p.risk_threshold
    cfg.high_risk_threshold = p.high_risk_threshold
    cfg.signal_weights = dict(p.signal_weights)
    return cfg


# Backwards-compatible alias (Phase 1 called it "mode").
def set_mode(cfg: Config, mode: str) -> Config:
    return set_profile(cfg, mode)


def set_value(cfg: Config, key: str, value: str) -> Config:
    """Set a single config value from a CLI string (with type coercion)."""
    key = key.lower().replace("-", "_")
    bool_true = {"1", "true", "on", "yes"}
    bool_false = {"0", "false", "off", "no"}

    if key in {"profile", "protection_mode", "mode"}:
        if value.upper() == "PERMISSIVE":
            value = "RELAXED"
        return set_profile(cfg, value)
    if key in {"screening_mode"}:
        v = value.upper()
        if v not in ("DRY_RUN", "ACTIVE"):
            raise ConfigError("screening_mode must be DRY_RUN or ACTIVE")
        cfg.screening_mode = v
        cfg._validate()
        return cfg
    if not hasattr(cfg, key):
        raise ConfigError(f"Unknown configuration key: {key}")
    if key in {"default_country", "color_enabled", "database_path", "pid_file", "log_file", "run_dir", "daemon_log_file", "socket_path"}:
        setattr(cfg, key, value)
    elif key in {"risk_threshold", "high_risk_threshold", "recent_window_seconds", "heartbeat_interval", "event_queue_size", "shutdown_timeout", "status_refresh_interval", "max_log_size", "max_log_files", "screening_timeout_ms"}:
        try:
            # Support suffix for max_log_size like 2MB
            if key == "max_log_size" and isinstance(value, str) and value.strip().upper().endswith("MB"):
                iv = int(float(value.strip()[:-2].strip()) * 1024 * 1024)
            elif key == "max_log_size" and isinstance(value, str) and value.strip().upper().endswith("KB"):
                iv = int(float(value.strip()[:-2].strip()) * 1024)
            else:
                iv = int(value)
        except ValueError as exc:
            raise ConfigError(f"{key} must be an integer.") from exc
        setattr(cfg, key, iv)
    elif key in {"logging_enabled", "output_json", "quiet", "daemon_enabled", "ipc_enabled", "screening_enabled"}:
        v = value.lower()
        if v in bool_true:
            setattr(cfg, key, True)
        elif v in bool_false:
            setattr(cfg, key, False)
        else:
            raise ConfigError(f"{key} must be true or false.")
    elif key in {"history_weight", "report_weight", "pattern_weight"}:
        try:
            fv = float(value)
        except ValueError as exc:
            raise ConfigError(f"{key} must be a number.") from exc
        setattr(cfg, key, fv)
    elif key == "signal_weights":
        # Accept a compact form: name=value,name=value,...
        try:
            pairs = [p.strip() for p in value.split(",") if p.strip()]
            w = dict(cfg.signal_weights)
            for p in pairs:
                if "=" not in p:
                    raise ConfigError(f"signal_weights entries must be name=value (got '{p}')")
                name, val = p.split("=", 1)
                w[name.strip()] = int(val.strip())
            cfg.signal_weights = w
        except ValueError as exc:
            raise ConfigError(f"Invalid signal_weights format: {exc}") from exc
    else:
        raise ConfigError(f"Setting '{key}' is not directly configurable via CLI.")
    cfg._validate()
    return cfg
