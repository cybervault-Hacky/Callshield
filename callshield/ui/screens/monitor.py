"""Live Monitor.

Shows the real event stream recorded by the daemon and the engine. The screen
never blocks: it polls bounded queries on the refresh interval and renders
"Waiting for events..." while nothing has been recorded. When the daemon is not
running the stored events are still shown, clearly labelled as stored data.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .. import formatters as fmt
from ..components import Column, kv_block, paragraph, section_title, status_bar, Surface, table
from .base import Action, Screen, empty_state, stay

MAX_ROWS = 12


class LiveMonitorScreen(Screen):
    """Non-blocking view of recent events and screening activity."""

    name = "monitor"
    title_key = "monitor.title"
    live = True

    def __init__(self, ctx: Any) -> None:
        Screen.__init__(self, ctx)
        self.events: List[Dict[str, Any]] = []
        self.screening: List[Dict[str, Any]] = []
        self.metrics: Dict[str, Any] = {}
        self.daemon_state = "UNKNOWN"
        self.connected = False
        self.last_refresh: Optional[float] = None
        self.errors: List[str] = []

    # ------------------------------------------------------------ data load
    def refresh(self) -> None:
        self.errors = []
        backend = self.backend
        self.daemon_state, _pid = backend.daemon_state()

        metrics = backend.daemon_metrics()
        self.connected = bool(metrics.ok and metrics.source != "offline")
        self.metrics = metrics.data if metrics.ok else {}
        if not metrics.ok:
            self.errors.append(metrics.error)

        events = backend.recent_events(limit=MAX_ROWS)
        if events.ok:
            self.events = list(events.data or [])
        else:
            self.events = []
            self.errors.append(events.error)

        screening = backend.recent_screening_events(limit=MAX_ROWS)
        self.screening = list(screening.data or []) if screening.ok else []

        self.last_refresh = time.localtime()

    def on_enter(self) -> None:
        self.refresh()

    # ---------------------------------------------------------------- parts
    def _counters(self, surface: Surface) -> List[str]:
        t = self.t
        data = self.metrics
        return kv_block(
            surface,
            [
                (t("main.field.events"), data.get("received")),
                (t("main.field.high_risk"), data.get("high_risk_count")),
                (t("main.field.blocks"), data.get("blocked_recommendations")),
                (t("main.field.queue"), "{0}/{1}".format(
                    fmt.integer(data.get("queue_size")),
                    fmt.integer(data.get("queue_max")))),
                (t("main.field.uptime"), data.get("uptime_human")),
            ],
        )

    def _event_table(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("monitor.stream"))]
        if not self.events:
            out.extend(empty_state(surface, t("monitor.waiting")))
            return out
        rows = [
            [
                fmt.timestamp(row.get("timestamp"), short=True),
                fmt.masked(row.get("number")),
                str(row.get("event_type") or ""),
                fmt.integer(row.get("risk_score")),
                fmt.status_word(row.get("action")),
                str(row.get("source") or ""),
            ]
            for row in self.events
        ]
        out.extend(
            table(
                surface,
                [
                    Column(t("common.time"), min_width=8, priority=3),
                    Column(t("common.number"), min_width=8, priority=3),
                    Column(t("common.action"), min_width=6, priority=2),
                    Column(t("common.score"), align="right", min_width=3, priority=2),
                    Column(t("common.verdict"), min_width=5, priority=1),
                    Column(t("monitor.source"), min_width=4, priority=1),
                ],
                rows,
                empty_message=t("monitor.waiting"),
            )
        )
        return out

    def _screening_table(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("monitor.screening_stream"))]
        if not self.screening:
            out.extend(empty_state(surface, t("monitor.waiting")))
            return out
        rows = [
            [
                fmt.timestamp(row.get("timestamp"), short=True),
                fmt.masked(row.get("number")),
                fmt.integer(row.get("risk_score")),
                fmt.status_word(row.get("recommended_action")),
                fmt.status_word(row.get("applied_action")),
                fmt.yes_no(row.get("actually_rejected")),
            ]
            for row in self.screening
        ]
        out.extend(
            table(
                surface,
                [
                    Column(t("common.time"), min_width=8, priority=3),
                    Column(t("common.number"), min_width=8, priority=3),
                    Column(t("common.score"), align="right", min_width=3, priority=2),
                    Column(t("blocks.recommended"), min_width=6, priority=2),
                    Column(t("blocks.applied"), min_width=6, priority=1),
                    Column(t("blocks.rejected"), min_width=3, priority=1),
                ],
                rows,
                empty_message=t("monitor.waiting"),
            )
        )
        return out

    # --------------------------------------------------------------- render
    def body(self, surface: Surface) -> List[str]:
        t = self.t
        lines = status_bar(
            surface,
            [
                (t("main.field.daemon"), self.daemon_state),
                (t("common.status"), "ONLINE" if self.connected else "OFFLINE"),
            ],
        )
        if not self.connected:
            lines.extend(paragraph(surface, t("monitor.daemon_offline"), role="warn"))
        lines.append("")
        lines.extend(self._counters(surface))
        lines.append("")
        lines.extend(self._event_table(surface))
        lines.append("")
        lines.extend(self._screening_table(surface))
        lines.append("")
        if self.last_refresh is not None:
            lines.append(
                surface.style(
                    "{0}: {1}".format(
                        t("monitor.refreshed"),
                        time.strftime("%H:%M:%S", self.last_refresh)),
                    "muted",
                )
            )
        for error in self.errors[:2]:
            lines.append(surface.style(fmt.truncate(error, surface.width), "muted"))
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        lines.extend(paragraph(surface, t("main.no_android"), role="muted"))
        return lines

    def hints(self) -> List[str]:
        return [self.t("monitor.hint"), self.t("nav.quit")]

    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return None


__all__ = ["LiveMonitorScreen", "MAX_ROWS"]
