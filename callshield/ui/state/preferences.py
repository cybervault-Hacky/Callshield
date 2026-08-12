"""Interface preferences.

These are *presentation* settings only: language, appearance, animation,
refresh rate, default scan mode and notifications. They live in their own
JSON file (``ui_state.json``) next to the database, and are deliberately kept
apart from :mod:`callshield.config`, which owns the security configuration.

This module therefore never imports the engine, the databases, the policy
state or the protection settings. The worst possible outcome of a corrupted
preferences file is that the interface falls back to its defaults; nothing
about protection behaviour can change from here.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from typing import Any, Dict, Optional

from ..i18n import DEFAULT_LANGUAGE, normalize_language

#: Bumped only when the on-disk shape changes in an incompatible way.
SCHEMA_VERSION = 1

#: File name used for the interface state, inside the CALLSHIELD data dir.
STATE_FILENAME = "ui_state.json"

#: Environment override, mainly for tests and unusual Termux layouts.
STATE_ENV_VAR = "CALLSHIELD_UI_STATE"

#: Largest state file we are willing to parse (a few hundred bytes are used).
MAX_STATE_BYTES = 64 * 1024

APPEARANCE_CHOICES = ("DARK", "LIGHT", "SYSTEM")
SCAN_MODE_CHOICES = ("BASIC", "ADVANCED")
#: Rendered in this order by the settings screen; ``0`` means manual refresh.
REFRESH_CHOICES = (1, 2, 5, 10, 0)

DEFAULT_APPEARANCE = "DARK"
DEFAULT_SCAN_MODE = "BASIC"
DEFAULT_REFRESH_SECONDS = 2


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
    return default


def _coerce_choice(value: Any, choices: Any, default: str) -> str:
    try:
        text = str(value).strip().upper()
    except Exception:  # noqa: BLE001 - display preference, never fatal
        return default
    return text if text in choices else default


def _coerce_refresh(value: Any) -> int:
    try:
        if isinstance(value, bool):
            raise TypeError
        seconds = int(value)
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_SECONDS
    return seconds if seconds in REFRESH_CHOICES else DEFAULT_REFRESH_SECONDS


@dataclass
class UIPreferences:
    """One user's interface preferences. Presentation only."""

    schema_version: int = SCHEMA_VERSION
    language: str = DEFAULT_LANGUAGE
    appearance: str = DEFAULT_APPEARANCE
    animation: bool = True
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS
    default_scan_mode: str = DEFAULT_SCAN_MODE
    notifications: bool = True

    # ------------------------------------------------------------ coercion
    def normalized(self) -> "UIPreferences":
        """Return a copy with every field forced back into a legal value."""

        return UIPreferences(
            schema_version=SCHEMA_VERSION,
            language=normalize_language(self.language),
            appearance=_coerce_choice(
                self.appearance, APPEARANCE_CHOICES, DEFAULT_APPEARANCE
            ),
            animation=_coerce_bool(self.animation, True),
            refresh_seconds=_coerce_refresh(self.refresh_seconds),
            default_scan_mode=_coerce_choice(
                self.default_scan_mode, SCAN_MODE_CHOICES, DEFAULT_SCAN_MODE
            ),
            notifications=_coerce_bool(self.notifications, True),
        )

    @property
    def manual_refresh(self) -> bool:
        """True when live screens should only refresh on request."""

        return _coerce_refresh(self.refresh_seconds) == 0

    # -------------------------------------------------------- serialisation
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def field_names(cls) -> Any:
        return tuple(item.name for item in fields(cls))

    @classmethod
    def from_mapping(cls, data: Any) -> "UIPreferences":
        """Build preferences from untrusted JSON. Unknown keys are dropped."""

        prefs = cls()
        if isinstance(data, dict):
            known = set(cls.field_names())
            for key, value in data.items():
                if key in known and key != "schema_version":
                    setattr(prefs, key, value)
        return prefs.normalized()


def preferences_path(cfg: Any) -> str:
    """Absolute path of the interface state file.

    It sits beside the database so a Termux install keeps everything under one
    directory, and it is never the security configuration file.
    """

    override = (os.environ.get(STATE_ENV_VAR) or "").strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    database = str(getattr(cfg, "database_path", "") or "")
    directory = os.path.dirname(os.path.abspath(os.path.expanduser(database)))
    if not directory:
        directory = os.path.abspath(".")
    return os.path.join(directory, STATE_FILENAME)


class PreferencesStore:
    """Load and save :class:`UIPreferences`. Touches one JSON file, nothing else.

    Every failure mode is non-fatal: a missing, unreadable, oversized, invalid
    or hostile file simply yields defaults, with ``recovered`` set so the
    interface can tell the user once.
    """

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg
        self.path = preferences_path(cfg)
        #: True when the last load had to fall back to defaults.
        self.recovered = False
        #: Text of the last read/write problem, or ``None``.
        self.last_error: Optional[str] = None

    # ------------------------------------------------------------ reading
    def load(self) -> UIPreferences:
        self.recovered = False
        self.last_error = None
        try:
            if not os.path.isfile(self.path):
                return UIPreferences()
            if os.path.getsize(self.path) > MAX_STATE_BYTES:
                raise ValueError("interface state file is too large")
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (OSError, UnicodeError, ValueError) as exc:
            self.recovered = True
            self.last_error = str(exc)[:200]
            return UIPreferences()

        if not isinstance(raw, dict):
            self.recovered = True
            self.last_error = "interface state is not an object"
            return UIPreferences()
        return UIPreferences.from_mapping(raw)

    # ------------------------------------------------------------ writing
    def save(self, prefs: UIPreferences) -> bool:
        """Persist ``prefs``. Returns True on success; never raises."""

        self.last_error = None
        payload = prefs.normalized().to_dict()
        try:
            directory = os.path.dirname(self.path)
            if directory and not os.path.isdir(directory):
                os.makedirs(directory, exist_ok=True)
            text = json.dumps(payload, indent=2, sort_keys=True)
            temporary = self.path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(text + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except (OSError, UnicodeError, TypeError, ValueError) as exc:
            self.last_error = str(exc)[:200]
            return False
        return True

    def reset(self) -> UIPreferences:
        """Restore defaults. Only the interface state file is rewritten."""

        defaults = UIPreferences()
        self.save(defaults)
        self.recovered = False
        return defaults


__all__ = [
    "APPEARANCE_CHOICES",
    "DEFAULT_APPEARANCE",
    "DEFAULT_REFRESH_SECONDS",
    "DEFAULT_SCAN_MODE",
    "MAX_STATE_BYTES",
    "PreferencesStore",
    "REFRESH_CHOICES",
    "SCAN_MODE_CHOICES",
    "SCHEMA_VERSION",
    "STATE_ENV_VAR",
    "STATE_FILENAME",
    "UIPreferences",
    "preferences_path",
]
