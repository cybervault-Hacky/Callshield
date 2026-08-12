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
from ..components import kv_block, paragraph, section_title, status_bar, Surface
from .base import Action, Screen, stay

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

    @staticmethod
    def _clock(value: Any) -> str:
        """Format a stored timestamp as ``HH:MM:SS`` without inventing data."""

        text = fmt.timestamp(value)
        if text == fmt.PLACEHOLDER:
            return text
        for separator in ("T", " "):
            if separator in text:
                text = text.split(separator, 1)[1]
                break
        text = text.split("+", 1)[0].split(".", 1)[0]
        if len(text) >= 8:
            return text[:8]
        return fmt.timestamp(value, short=True)

    def _stream_rows(self, surface: Surface, rows: Sequence[Dict[str, Any]],
                     kind: str = "event") -> List[str]:
        """One compact ``TIME  EVENT  MASKED  SCORE`` line per record.

        Only fields the local database actually records are shown; nothing is
        synthesised. Events carry ``verdict`` and ``action``, screening rows
        carry ``recommended_action`` / ``applied_action``.
        """

        t = self.t
        out: List[str] = []
        for row in rows:
            stamp = self._clock(row.get("timestamp"))
            event = str(row.get("verdict")
                        or row.get("recommended_action")
                        or row.get("action") or "--")
            number = fmt.masked(row.get("number"))
            score = fmt.integer(row.get("risk_score"))
            action = fmt.status_word(row.get("action")
                                     or row.get("applied_action") or "")
            line = "{0}  {1:<12} {2}".format(
                stamp, fmt.truncate(event, 12), number)
            if score != fmt.PLACEHOLDER:
                line += "  {0:>3}".format(score)
            if action:
                line += "  " + surface.status(action)
            out.append(fmt.truncate(line, surface.width))
        if not out:
            out.append(surface.style(t("monitor.waiting"), "muted"))
        return out

    def _event_stream(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("monitor.stream"))]
        out.extend(self._stream_rows(surface, self.events))
        return out

    def _screening_stream(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("monitor.screening_stream"))]
        out.extend(self._stream_rows(surface, self.screening))
        return out

    # --------------------------------------------------------------- render
    def body(self, surface: Surface) -> List[str]:
        t = self.t
        lines = status_bar(
            surface,
            [
                (t("common.status"), "CONNECTED" if self.connected else "OFFLINE"),
                (t("main.field.daemon"), self.daemon_state),
            ],
        )
        if not self.connected:
            lines.extend(paragraph(surface, t("monitor.daemon_offline"), role="warn"))
        lines.append("")
        lines.extend(self._counters(surface))
        lines.append("")
        lines.extend(self._event_stream(surface))
        lines.append("")
        lines.extend(self._screening_stream(surface))
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
