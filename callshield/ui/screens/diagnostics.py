"""Diagnostics screen.

A read-only front end for :func:`callshield.doctor.run_doctor`. Repairs are
deliberately not offered here — ``callshield doctor --repair`` remains the one
place that can modify files, so the interface cannot change anything on disk.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .. import formatters as fmt
from ..components import Column, kv_block, paragraph, status_bar, Surface, table
from .base import Action, Screen, empty_state, section_title, stay


def _report_to_dict(report: Any) -> Dict[str, Any]:
    """Accept either a ``DoctorReport`` or a plain dict."""

    if report is None:
        return {}
    if isinstance(report, dict):
        return report
    to_dict = getattr(report, "to_dict", None)
    if callable(to_dict):
        try:
            return dict(to_dict())
        except Exception:  # pragma: no cover - defensive
            return {}
    return {}


class DiagnosticsScreen(Screen):
    """System health checks."""

    name = "diagnostics"
    title_key = "diagnostics.title"

    def __init__(self, ctx: Any) -> None:
        Screen.__init__(self, ctx)
        self.columns = (
            Column("Check", min_width=8, priority=3),
            Column(ctx.t("common.status"), min_width=7, priority=3),
            Column("Detail", min_width=10, priority=1),
        )
        self.report: Dict[str, Any] = {}
        self.available = False

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        result = self.backend.doctor()
        if not result.ok:
            self.available = False
            self.report = {}
            self.set_message(result.error or self.t("error.generic"), "err")
            return
        self.report = _report_to_dict(result.data)
        self.available = bool(self.report.get("checks"))
        if not self.available:
            self.set_message(self.t("error.corrupt_data"), "warn")
        else:
            self.clear_message()

    def on_enter(self) -> None:
        self.refresh()

    # ---------------------------------------------------------------- render
    def _checks(self) -> List[Dict[str, Any]]:
        checks = self.report.get("checks") or []
        return [check for check in checks if isinstance(check, dict)]

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        if not self.available:
            lines = list(empty_state(surface, t("common.unavailable")))
            lines.extend(paragraph(surface, t("error.database_unavailable"), role="muted"))
            return lines

        checks = self._checks()
        problems = [
            check
            for check in checks
            if str(check.get("status", "")).upper() in ("WARNING", "ERROR")
        ]
        overall = fmt.status_word(self.report.get("status"))

        lines = [section_title(surface, t("diagnostics.summary"))]
        lines.extend(
            status_bar(
                surface,
                [
                    (t("common.status"), overall),
                    (t("common.total"), str(len(checks))),
                ],
            )
        )
        lines.append("")
        lines.append(
            surface.style(
                t("diagnostics.healthy")
                if not problems
                else t("diagnostics.issues", count=len(problems)),
                "ok" if not problems else "warn",
            )
        )
        lines.append("")
        lines.append(section_title(surface, t("diagnostics.title")))

        rows: List[Sequence[Any]] = []
        for check in checks:
            name = fmt.text_or_placeholder(check.get("name"))
            if check.get("repaired"):
                name = "{0} *".format(name)
            rows.append(
                [
                    name,
                    fmt.status_word(check.get("status")),
                    fmt.text_or_placeholder(check.get("detail")),
                ]
            )
        lines.extend(
            table(surface, self.columns, rows, empty_message=t("common.empty"))
        )
        lines.append("")
        lines.extend(
            kv_block(
                surface,
                [(t("main.field.version"), self.ctx.version)],
            )
        )
        lines.extend(paragraph(surface, t("screening.not_verified"), role="muted"))
        lines.extend(paragraph(surface, t("error.no_network"), role="muted"))
        return lines

    # ----------------------------------------------------------------- input
    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.set_message(self.t("diagnostics.running"), "info")
            self.refresh()
            return stay()
        return None

    def hints(self) -> List[str]:
        return [self.t("nav.refresh") + " (r)", self.t("nav.back"),
                self.t("nav.quit")]


__all__ = ["DiagnosticsScreen"]
