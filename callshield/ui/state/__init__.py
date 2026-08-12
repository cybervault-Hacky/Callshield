"""Interface state.

Two clearly separated concerns live here:

``preferences``
    Presentation settings stored in ``ui_state.json``. Never touches the
    security configuration, the databases or the daemon.

``backend``
    The only door between the interface and CALLSHIELD. Delegates to the
    existing CLI handlers, engines and databases; performs no network
    communication and contains no business logic.
"""

from __future__ import annotations

from .backend import Backend, Result
from .preferences import (
    APPEARANCE_CHOICES,
    PreferencesStore,
    REFRESH_CHOICES,
    SCAN_MODE_CHOICES,
    UIPreferences,
    preferences_path,
)

__all__ = [
    "APPEARANCE_CHOICES",
    "Backend",
    "PreferencesStore",
    "REFRESH_CHOICES",
    "Result",
    "SCAN_MODE_CHOICES",
    "UIPreferences",
    "preferences_path",
]
