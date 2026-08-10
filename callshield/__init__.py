"""CALLSHIELD — local fraud-number analysis and protection foundation (Phase 1).

Phase 1 provides a CLI, local SQLite database, number normalization, blacklist/
whitelist management, a local reputation engine, deterministic risk scoring,
event logging, configuration, and a background-process foundation.

Phase 1 does NOT intercept or reject live phone calls.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["__version__", "PACKAGE_ROOT", "DATA_DIR", "LOG_DIR"]

# Version is read from the VERSION file at package root for single-sourcing.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_VERSION_FILE = _PACKAGE_ROOT / "VERSION"
try:
    __version__ = _VERSION_FILE.read_text(encoding="utf-8").strip()
except OSError:
    __version__ = "0.0.0"

PACKAGE_ROOT: Path = _PACKAGE_ROOT

# Directories used for runtime state. They can be overridden with environment
# variables so tests (and alternate installs) can redirect state.
DATA_DIR: Path = Path(os.environ.get("CALLSHIELD_DATA_DIR", PACKAGE_ROOT / "data"))
LOG_DIR: Path = Path(os.environ.get("CALLSHIELD_LOG_DIR", PACKAGE_ROOT / "logs"))

# Ensure directories exist on import so downstream code can rely on them.
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
