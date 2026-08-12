"""History browser.

Every query here is bounded: the backend caps the row count and the pager only
ever renders one page at a time, so a large database cannot stall the
interface. Numbers are masked before they reach the screen.
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

#: Hard upper bound for any history query issued by the interface.
QUERY_LIMIT = 500


class EventHistoryScreen(ListScreen):
    """The local event log, newest first."""

    name = "history_events"
    title_key = "history.events"
    empty_key = "history.none"

    def __init__(self, ctx: Any) -> None:
        self.columns = (
            Column(ctx.t("common.time"), min_width=10, priority=3),
            Column(ctx.t("common.number"), min_width=10, priority=3),
            Column("Type", min_width=6, priority=2),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=1),
            Column(ctx.t("common.action"), min_width=5, priority=1),
            Column(ctx.t("monitor.source"), min_width=6, priority=1),
        )
        ListScreen.__init__(self, ctx)

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.recent_events(limit=QUERY_LIMIT)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        return [
            [
                fmt.timestamp(row.get("timestamp"), short=True),
                fmt.masked(row.get("number")),
                fmt.status_word(row.get("event_type")),
                fmt.integer(row.get("risk_score")),
                fmt.status_word(row.get("action")),
                fmt.text_or_placeholder(row.get("source")),
            ]
            for row in result.data or []
        ]

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.t("history.events")),
            surface.style(self.t("common.masked_note"), "muted"),
        ]

    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return ListScreen.handle(self, key)


class ScreeningHistoryScreen(ListScreen):
    """Screening events recorded by the daemon bridge."""

    name = "history_screening"
    title_key = "history.screening"
    empty_key = "history.none"

    def __init__(self, ctx: Any) -> None:
        self.columns = (
            Column(ctx.t("common.time"), min_width=10, priority=3),
            Column(ctx.t("common.number"), min_width=10, priority=3),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=1),
            Column(ctx.t("common.action"), min_width=5, priority=2),
            Column(ctx.t("monitor.source"), min_width=6, priority=1),
        )
        ListScreen.__init__(self, ctx)

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.recent_screening_events(limit=QUERY_LIMIT)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        return [
            [
                fmt.timestamp(row.get("timestamp"), short=True),
                fmt.masked(row.get("number")),
                fmt.integer(row.get("risk_score")),
                fmt.status_word(row.get("action")),
                fmt.text_or_placeholder(row.get("source")),
            ]
            for row in result.data or []
        ]

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.t("history.screening")),
            surface.style(self.t("screening.not_verified"), "muted"),
        ]

    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return ListScreen.handle(self, key)


class NumberHistoryScreen(ListScreen):
    """Everything the local database recorded for one number."""

    name = "history_number"
    title_key = "history.number"
    empty_key = "history.none"

    def __init__(self, ctx: Any, number: str) -> None:
        self.columns = (
            Column(ctx.t("common.time"), min_width=10, priority=3),
            Column("Type", min_width=6, priority=2),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=1),
            Column(ctx.t("common.action"), min_width=5, priority=2),
            Column(ctx.t("monitor.source"), min_width=6, priority=1),
        )
        ListScreen.__init__(self, ctx)
        self.number = number
        self.total = 0

    def refresh(self) -> None:
        count = self.backend.number_history_count(self.number)
        self.total = int(count.data or 0) if count.ok else 0
        ListScreen.refresh(self)

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.number_history(self.number, limit=QUERY_LIMIT)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        return [
            [
                fmt.timestamp(row.get("timestamp"), short=True),
                fmt.status_word(row.get("event_type")),
                fmt.integer(row.get("risk_score")),
                fmt.status_word(row.get("action")),
                fmt.text_or_placeholder(row.get("source")),
            ]
            for row in result.data or []
        ]

    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("history.number"))]
        lines.extend(
            kv_block(
                surface,
                [
                    (t("common.number"), fmt.masked(self.number)),
                    (t("scan.field.events"), fmt.integer(self.total)),
                ],
            )
        )
        return lines

    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return ListScreen.handle(self, key)


class HistoryScreen(MenuScreen):
    """History menu."""

    name = "history"
    title_key = "history.title"

    def __init__(self, ctx: Any) -> None:
        MenuScreen.__init__(self, ctx)
        self.totals = {"events": 0, "high_risk": 0, "blocks": 0}

    def refresh(self) -> None:
        metrics = self.backend.event_metrics()
        data = metrics.data or {} if metrics.ok else {}
        self.totals = {
            "events": int(data.get("total") or 0),
            "high_risk": int(data.get("high_risk") or 0),
            "blocks": int(data.get("block_recommendations") or 0),
        }
        if not metrics.ok:
            self.set_message(metrics.error, "err")

    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("history.title"))]
        lines.extend(
            kv_block(
                surface,
                [
                    (t("main.field.events"), fmt.integer(self.totals["events"])),
                    (t("main.field.high_risk"), fmt.integer(self.totals["high_risk"])),
                    (t("main.field.blocks"), fmt.integer(self.totals["blocks"])),
                ],
            )
        )
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        return lines

    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        return [
            MenuItem("events", t("history.events"),
                     status=fmt.integer(self.totals["events"])),
            MenuItem("screening", t("history.screening")),
            MenuItem("number", t("history.number")),
        ]

    def activate(self, item: MenuItem) -> Optional[Action]:
        if item.key == "events":
            return push(EventHistoryScreen(self.ctx))
        if item.key == "screening":
            return push(ScreeningHistoryScreen(self.ctx))
        if item.key == "number":
            number = self.ctx.ask(self.t("prompt.number"))
            if not number:
                self.set_message(self.t("prompt.empty_input"), "warn")
                return stay()
            check = self.backend.normalize(number)
            if not check.ok:
                self.set_message(self.t("prompt.invalid_number"), "warn")
                return stay()
            normalized = (check.data or {}).get("normalized") or number
            return push(NumberHistoryScreen(self.ctx, normalized))
        return None


__all__ = [
    "EventHistoryScreen",
    "HistoryScreen",
    "NumberHistoryScreen",
    "QUERY_LIMIT",
    "ScreeningHistoryScreen",
]
