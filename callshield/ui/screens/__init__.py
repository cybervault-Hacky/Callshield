"""Screen registry.

Screens are imported lazily by :func:`make_screen` so that starting the
interface does not pay for modules the user never opens. The registry is a
plain mapping of key -> (module, class name); there is no dynamic evaluation of
user input anywhere in this package.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Optional, Tuple

from .base import (
    Action,
    DetailScreen,
    HOME,
    ListScreen,
    MenuItem,
    MenuScreen,
    POP,
    PUSH,
    QUIT,
    STAY,
    Screen,
    home,
    pop,
    push,
    quit_app,
    stay,
)

#: Screen key -> (module name relative to this package, class name).
REGISTRY: Dict[str, Tuple[str, str]] = {
    "dashboard": ("dashboard", "DashboardScreen"),
    "scan": ("scan", "ScanCenterScreen"),
    "monitor": ("monitor", "LiveMonitorScreen"),
    "daemon": ("daemon", "DaemonScreen"),
    "screening": ("screening", "ScreeningScreen"),
    "policy": ("policy", "PolicyScreen"),
    "reputation": ("reputation", "ReputationScreen"),
    "intelligence": ("intelligence", "IntelligenceScreen"),
    "blocks": ("blocks", "BlockScreen"),
    "reports": ("reports", "ReportScreen"),
    "history": ("history", "HistoryScreen"),
    "diagnostics": ("diagnostics", "DiagnosticsScreen"),
    "settings": ("settings", "SettingsScreen"),
    "about": ("about", "AboutScreen"),
}


def screen_class(key: str) -> Optional[type]:
    """Resolve a registry key to a screen class, or ``None`` when unknown."""

    entry = REGISTRY.get(str(key))
    if entry is None:
        return None
    module_name, class_name = entry
    module = importlib.import_module("." + module_name, __name__)
    return getattr(module, class_name, None)


def make_screen(key: str, ctx: Any) -> Optional[Screen]:
    """Instantiate a registered screen. Unknown keys return ``None``."""

    cls = screen_class(key)
    if cls is None:
        return None
    return cls(ctx)


__all__ = [
    "Action",
    "DetailScreen",
    "HOME",
    "ListScreen",
    "MenuItem",
    "MenuScreen",
    "POP",
    "PUSH",
    "QUIT",
    "REGISTRY",
    "STAY",
    "Screen",
    "home",
    "make_screen",
    "pop",
    "push",
    "quit_app",
    "screen_class",
    "stay",
]
