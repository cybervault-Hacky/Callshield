"""CALLSHIELD terminal interface (Phase 8.5).

This package contains presentation code only. Every value it renders is read
through the existing CLI helpers, service APIs, engines and databases; the UI
implements no detection, scoring, policy or persistence logic of its own and
performs no network communication.

Layout::

    ui/app.py          application shell and main loop
    ui/screens/        one module per screen
    ui/components/     reusable render helpers (panels, tables, menus)
    ui/navigation/     key decoding, screen stack, menu selection
    ui/theme/          palette, glyph tables, terminal capability probing
    ui/i18n/           translation dictionaries and lookup
    ui/state/          interface preferences (separate from security config)
    ui/formatters/     value formatting (durations, numbers, status words)
"""

from __future__ import annotations

__all__ = ["run"]


def run(cfg, argv=None):  # pragma: no cover - thin re-export
    """Launch the interface. Imported lazily to keep CLI start-up cheap."""

    from .app import run as _run

    return _run(cfg, argv=argv)
