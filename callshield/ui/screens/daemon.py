"""Daemon Control.

Start / stop / restart are delegated to the existing CLI handlers, which own
the pid file, the spawn logic and the IPC handshake. The interface never spawns
a second daemon, never signals a process directly and never writes a pid file.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .. import formatters as fmt
from ..components import kv_block, paragraph, section_title, Surface
from .base import (
    Action,
    MenuItem,
    MenuScreen,
    Screen,
    empty_state,
    push,
    stay,
)


def _output_message(result: Any, fallback: str) -> str:
    """Turn a CLI-handler Result into a single readable line."""

    if not getattr(result, "ok", False):
        return getattr(result, "error", "") or fallback
    data = result.data or {}
    text = str(data.get("output") or "").strip().replace("\n", "  ")
    if not text:
        text = fallback
    return fmt.truncate(text, 200)


class DaemonMetricsScreen(Screen):
    """Full metrics table, live from IPC or from the stored snapshot."""

    name = "daemon_metrics"
    title_key = "daemon.metrics"
    live = True

    FIELDS: Sequence[str] = (
        "uptime_human",
        "received",
        "processed",
        "failed",
        "dropped",
        "queue_size",
        "queue_max",
        "queue_peak",
        "high_risk_count",
        "blocked_recommendations",
        "memory_kb",
        "incoming_calls",
        "screened",
        "screening_timeouts",
        "bridge_errors",
        "screening_high_risk",
        "screening_allowed",
        "screening_unknown",
        "screening_block_recommended",
        "screening_blocked",
        "actually_rejected",
        "policy_errors",
    )

    def __init__(self, ctx: Any) -> None:
        Screen.__init__(self, ctx)
        self.data: Dict[str, Any] = {}
        self.source = ""

    def refresh(self) -> None:
        result = self.backend.daemon_metrics()
        self.data = result.data if result.ok else {}
        self.source = result.source if result.ok else ""
        if not result.ok:
            self.set_message(result.error, "err")

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        if not self.data:
            return list(empty_state(surface, t("common.unavailable")))
        rows = []
        for field in self.FIELDS:
            if field not in self.data:
                continue
            value = self.data[field]
            if field == "memory_kb":
                value = fmt.bytes_kb(value)
            rows.append((field, value))
        lines = [section_title(surface, t("daemon.metrics"))]
        lines.extend(kv_block(surface, rows))
        lines.append("")
        if self.source == "offline":
            lines.extend(paragraph(surface, t("error.daemon_unavailable"), role="warn"))
        lines.extend(paragraph(surface, t("daemon.android_note"), role="muted"))
        return lines

    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return None


class DaemonHealthScreen(Screen):
    """Health report; requires the daemon to answer over local IPC."""

    name = "daemon_health"
    title_key = "daemon.health"

    FIELDS: Sequence[str] = (
        "pid",
        "uptime_human",
        "db_status",
        "queue_size",
        "queue_max",
        "processed",
        "failed",
        "last_heartbeat_human",
        "memory_kb",
        "screened",
        "bridge_errors",
        "policy_errors",
        "screening_blocked",
        "actually_rejected",
    )

    def __init__(self, ctx: Any) -> None:
        Screen.__init__(self, ctx)
        self.data: Dict[str, Any] = {}
        self.available = False

    def refresh(self) -> None:
        result = self.backend.daemon_health()
        self.available = bool(result.ok)
        self.data = result.data if result.ok else {}
        if not result.ok:
            self.set_message(result.error, "warn")

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        if not self.available:
            lines = list(empty_state(surface, t("daemon.not_running")))
            lines.extend(paragraph(surface, t("error.daemon_unavailable"), role="muted"))
            return lines
        healthy = self.data.get("healthy")
        rows = [(t("common.status"), "HEALTHY" if healthy is not False else "WARNING")]
        for field in self.FIELDS:
            if field in self.data:
                value = self.data[field]
                if field == "memory_kb":
                    value = fmt.bytes_kb(value)
                rows.append((field, value))
        lines = [section_title(surface, t("daemon.health"))]
        lines.extend(kv_block(surface, rows, status_keys=(t("common.status"),)))
        lines.append("")
        lines.extend(paragraph(surface, t("daemon.android_note"), role="muted"))
        return lines

    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return None


class DaemonScreen(MenuScreen):
    """Daemon status plus lifecycle actions."""

    name = "daemon"
    title_key = "daemon.title"
    live = True

    def __init__(self, ctx: Any) -> None:
        MenuScreen.__init__(self, ctx)
        self.state = "UNKNOWN"
        self.pid: Optional[int] = None
        self.info: Dict[str, Any] = {}
        self.metrics: Dict[str, Any] = {}
        self.connected = False

    # ------------------------------------------------------------ data load
    def refresh(self) -> None:
        self.state, self.pid = self.backend.daemon_state()
        info = self.backend.daemon_info()
        self.connected = bool(info.ok)
        self.info = info.data if info.ok else {}
        metrics = self.backend.daemon_metrics()
        self.metrics = metrics.data if metrics.ok else {}

    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("daemon.status"))]
        enabled = bool(getattr(self.ctx.cfg, "daemon_enabled", True))
        rows = [
            (t("common.status"), self.state),
            (t("main.field.pid"), self.pid),
            (t("main.field.uptime"), self.metrics.get("uptime_human")),
            ("IPC", "ENABLED" if getattr(self.ctx.cfg, "ipc_enabled", True)
             else "DISABLED"),
            (t("common.enabled"), "ENABLED" if enabled else "DISABLED"),
            (t("main.field.queue"), "{0}/{1}".format(
                fmt.integer(self.metrics.get("queue_size")),
                fmt.integer(self.metrics.get("queue_max")))),
            (t("main.field.screening"), self.info.get("call_screening")),
            ("Android", "NOT VERIFIED"),
        ]
        lines.extend(
            kv_block(
                surface,
                rows,
                status_keys=(t("common.status"), "IPC", t("common.enabled"),
                             t("main.field.screening"), "Android"),
            )
        )
        if not enabled:
            lines.extend(paragraph(surface, t("daemon.disabled"), role="warn"))
        if self.state != "RUNNING":
            lines.extend(paragraph(surface, t("daemon.not_running"), role="warn"))
        lines.extend(paragraph(surface, t("daemon.android_note"), role="muted"))
        return lines

    # ---------------------------------------------------------------- menu
    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        running = self.state == "RUNNING"
        return [
            MenuItem("status", t("daemon.status"), status=self.state),
            MenuItem("start", t("daemon.start"), enabled=not running),
            MenuItem("stop", t("daemon.stop"), enabled=running),
            MenuItem("restart", t("daemon.restart")),
            MenuItem("health", t("daemon.health"), enabled=running),
            MenuItem("metrics", t("daemon.metrics")),
        ]

    def activate(self, item: MenuItem) -> Optional[Action]:
        t = self.t
        key = item.key

        if key == "status":
            self.refresh()
            self.rebuild()
            self.set_message(t("common.done"), "ok")
            return stay()

        if key == "metrics":
            return push(DaemonMetricsScreen(self.ctx))

        if key == "health":
            if self.state != "RUNNING":
                self.set_message(t("daemon.not_running"), "warn")
                return stay()
            return push(DaemonHealthScreen(self.ctx))

        if key == "start":
            if self.state == "RUNNING":
                self.set_message(t("common.done"), "info")
                return stay()
            self.set_message(t("daemon.starting"), "info")
            result = self.backend.start_daemon()
            self._apply(result, t("common.done"))
            return stay()

        if key == "stop":
            if not self.ctx.confirm(t("daemon.confirm_stop")):
                self.set_message(t("common.cancelled"), "info")
                return stay()
            self.set_message(t("daemon.stopping"), "info")
            result = self.backend.stop_daemon()
            self._apply(result, t("common.done"))
            return stay()

        if key == "restart":
            if not self.ctx.confirm(t("daemon.confirm_restart")):
                self.set_message(t("common.cancelled"), "info")
                return stay()
            if self.state == "RUNNING":
                stopped = self.backend.stop_daemon()
                if not getattr(stopped, "ok", False):
                    self._apply(stopped, t("common.done"))
                    return stay()
            result = self.backend.start_daemon()
            self._apply(result, t("common.done"))
            return stay()

        return None

    def _apply(self, result: Any, success: str) -> None:
        ok = getattr(result, "ok", False) and (result.data or {}).get("exit_code") == 0
        message = _output_message(result, success)
        self.set_message(message, "ok" if ok else "err")
        self.refresh()
        self.rebuild()

    def hints(self) -> List[str]:
        return [self.t("nav.hint"), self.t("nav.number_hint")]


__all__ = ["DaemonHealthScreen", "DaemonMetricsScreen", "DaemonScreen"]
