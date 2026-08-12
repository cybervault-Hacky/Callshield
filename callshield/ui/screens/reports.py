"""Report Center.

User reports are stored locally through the existing ``report`` CLI handler.
Nothing is uploaded, shared or synchronised: there is no remote reporting
service and no network call anywhere in this module.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from .. import formatters as fmt
from ..components import Column, kv_block, paragraph, Surface
from .base import (
    Action,
    ListScreen,
    MenuItem,
    MenuScreen,
    push,
    section_title,
    stay,
)


class NumberReportsScreen(ListScreen):
    """Reports stored for one number."""

    name = "reports_number"
    title_key = "reports.recent"
    empty_key = "reports.none"

    def __init__(self, ctx: Any, number: str) -> None:
        self.columns = (
            Column(ctx.t("common.time"), min_width=10, priority=3),
            Column(ctx.t("common.number"), min_width=10, priority=2),
            Column(ctx.t("common.reason"), min_width=10, priority=1),
        )
        ListScreen.__init__(self, ctx)
        self.number = number

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.reports(self.number, limit=200)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        return [
            [
                fmt.timestamp(row.get("created_at"), short=True),
                fmt.masked(row.get("number")),
                fmt.text_or_placeholder(row.get("reason")),
            ]
            for row in result.data or []
        ]

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.t("reports.recent")),
            surface.style(
                "{0}: {1}".format(self.t("common.number"), fmt.masked(self.number)),
                "muted",
            ),
            surface.style(self.t("reports.local_only"), "muted"),
        ]


class RecentReportsScreen(ListScreen):
    """Report activity taken from the local event log."""

    name = "reports_recent"
    title_key = "reports.recent"
    empty_key = "reports.none"

    def __init__(self, ctx: Any) -> None:
        self.columns = (
            Column(ctx.t("common.time"), min_width=10, priority=3),
            Column(ctx.t("common.number"), min_width=10, priority=3),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=1),
            Column(ctx.t("common.action"), min_width=6, priority=1),
        )
        ListScreen.__init__(self, ctx)

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.recent_events(limit=500)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        rows = []
        for event in result.data or []:
            if str(event.get("event_type")) != "USER_REPORT":
                continue
            rows.append(
                [
                    fmt.timestamp(event.get("timestamp"), short=True),
                    fmt.masked(event.get("number")),
                    fmt.integer(event.get("risk_score")),
                    fmt.status_word(event.get("action")),
                ]
            )
        return rows

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.t("reports.recent")),
            surface.style(self.t("reports.local_only"), "muted"),
        ]


class ReportScreen(MenuScreen):
    """Report Center menu."""

    name = "reports"
    title_key = "reports.title"

    def __init__(self, ctx: Any) -> None:
        MenuScreen.__init__(self, ctx)
        self.report_events = 0

    def refresh(self) -> None:
        result = self.backend.recent_events(limit=500)
        events = result.data or [] if result.ok else []
        self.report_events = sum(
            1 for event in events if str(event.get("event_type")) == "USER_REPORT"
        )

    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        lines: List[str] = []
        lines.extend(
            kv_block(
                surface,
                [(t("reports.count"), fmt.integer(self.report_events))],
            )
        )
        lines.extend(paragraph(surface, t("reports.local_only"), role="muted"))
        lines.extend(paragraph(surface, t("error.no_network"), role="muted"))
        return lines

    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        return [
            MenuItem("submit", t("reports.submit")),
            MenuItem("recent", t("reports.recent"),
                     status=fmt.integer(self.report_events)),
            MenuItem("number", t("history.number")),
        ]

    def activate(self, item: MenuItem) -> Optional[Action]:
        t = self.t
        key = item.key

        if key == "recent":
            return push(RecentReportsScreen(self.ctx))

        number = self.ctx.ask(t("prompt.number"))
        if not number:
            self.set_message(t("prompt.empty_input"), "warn")
            return stay()
        check = self.backend.normalize(number)
        if not check.ok:
            self.set_message(t("prompt.invalid_number"), "warn")
            return stay()
        normalized = (check.data or {}).get("normalized") or number

        if key == "number":
            return push(NumberReportsScreen(self.ctx, normalized))

        if key == "submit":
            reason = self.ctx.ask(t("reports.prompt_reason")) or ""
            if not self.ctx.confirm(t("prompt.confirm")):
                self.set_message(t("common.cancelled"), "info")
                return stay()
            result = self.backend.add_report(normalized, reason)
            ok = result.ok and (result.data or {}).get("exit_code") == 0
            self.set_message(
                t("reports.saved") if ok else t("error.generic"),
                "ok" if ok else "err",
            )
            self.refresh()
            self.rebuild()
            return stay()

        return None


__all__ = ["NumberReportsScreen", "RecentReportsScreen", "ReportScreen"]
