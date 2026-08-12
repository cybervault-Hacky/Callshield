"""Screening Center.

Every state change is routed through the existing ``screening`` CLI handler, so
the safety rules stay exactly where they already live:

* ACTIVE mode keeps its blocking explicit confirmation prompt — the interface
  hands the real terminal to the CLI handler instead of answering for the user.
* Emergency off cannot be bypassed from here.
* CONNECTED refers to the local daemon IPC socket only. No Android device is
  ever described as verified.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .. import formatters as fmt
from ..components import kv_block, paragraph, section_title, status_bar, Surface
from .base import Action, MenuItem, MenuScreen, Screen, empty_state, push, stay


class ScreeningMetricsScreen(Screen):
    """Screening counters from the database (and the daemon when reachable)."""

    name = "screening_metrics"
    title_key = "screening.metrics"

    def __init__(self, ctx: Any) -> None:
        Screen.__init__(self, ctx)
        self.data: Dict[str, Any] = {}
        self.total = 0

    def refresh(self) -> None:
        result = self.backend.screening_metrics()
        self.data = result.data if result.ok else {}
        if not result.ok:
            self.set_message(result.error, "err")

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        if not self.data:
            return list(empty_state(surface, t("common.empty")))
        lines = [section_title(surface, t("screening.metrics"))]
        lines.extend(kv_block(surface, sorted(self.data.items())))
        lines.append("")
        lines.extend(paragraph(surface, t("screening.not_verified"), role="muted"))
        return lines

    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return None


class ScreeningHealthScreen(Screen):
    """Live screening health, only meaningful while the daemon is running."""

    name = "screening_health"
    title_key = "screening.health"

    def __init__(self, ctx: Any) -> None:
        Screen.__init__(self, ctx)
        self.data: Dict[str, Any] = {}
        self.connected = False

    def refresh(self) -> None:
        result = self.backend.ipc("screening_status")
        self.connected = bool(result.ok)
        self.data = result.data if result.ok else {}
        if not result.ok:
            self.set_message(result.error, "warn")

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("screening.health"))]
        lines.extend(
            status_bar(
                surface,
                [("IPC", "CONNECTED" if self.connected else "OFFLINE"),
                 ("Android", "NOT VERIFIED")],
            )
        )
        lines.append("")
        if not self.connected:
            lines.extend(empty_state(surface, t("daemon.not_running")))
            lines.extend(paragraph(surface, t("error.daemon_unavailable"), role="muted"))
            return lines
        lines.extend(kv_block(surface, sorted(self.data.items())))
        lines.append("")
        lines.extend(paragraph(surface, t("daemon.android_note"), role="muted"))
        lines.extend(paragraph(surface, t("screening.not_verified"), role="muted"))
        return lines

    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return None


class ScreeningScreen(MenuScreen):
    """Screening status and the mode/enable controls."""

    name = "screening"
    title_key = "screening.title"
    live = True

    def __init__(self, ctx: Any) -> None:
        MenuScreen.__init__(self, ctx)
        self.snapshot: Dict[str, Any] = {}
        self.live_data: Dict[str, Any] = {}
        self.connected = False
        self.daemon_state = "UNKNOWN"
        self.metrics: Dict[str, Any] = {}

    # ------------------------------------------------------------ data load
    def refresh(self) -> None:
        backend = self.backend
        self.snapshot = backend.policy_snapshot()
        self.daemon_state, _pid = backend.daemon_state()
        live = backend.ipc("screening_status") if self.daemon_state == "RUNNING" \
            else None
        self.connected = bool(live is not None and live.ok)
        self.live_data = live.data if (live is not None and live.ok) else {}
        metrics = backend.screening_metrics()
        self.metrics = metrics.data if metrics.ok else {}

    # ------------------------------------------------------------- derived
    @property
    def emergency(self) -> bool:
        return bool(self.snapshot.get("emergency_off"))

    @property
    def enabled(self) -> bool:
        return bool(self.snapshot.get("enabled"))

    @property
    def mode(self) -> str:
        return str(self.snapshot.get("mode") or "DRY_RUN")

    @property
    def auto_reject(self) -> bool:
        """True only when a call could really be rejected on this device."""

        return bool(
            self.enabled
            and self.mode == "ACTIVE"
            and self.snapshot.get("active_confirmed")
            and not self.emergency
            and self.connected
        )

    # --------------------------------------------------------------- render
    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("screening.status"))]
        rows = [
            (t("screening.status"), "ENABLED" if self.enabled else "DISABLED"),
            (t("common.mode"), self.mode),
            (t("common.policy"), self.snapshot.get("current")),
            (t("policy.emergency"), "ENGAGED" if self.emergency else "CLEAR"),
            (t("main.field.daemon"), self.daemon_state),
            ("IPC", "CONNECTED" if self.connected else "OFFLINE"),
            ("Auto Reject", "ARMED" if self.auto_reject else "DISABLED"),
            ("Android", "NOT VERIFIED"),
        ]
        lines.extend(
            kv_block(
                surface,
                rows,
                status_keys=(t("screening.status"), t("common.mode"),
                             t("policy.emergency"), t("main.field.daemon"),
                             "IPC", "Auto Reject", "Android"),
            )
        )
        lines.append("")
        counters = [
            (t("screening.status"), self.metrics.get("screened")),
            (t("blocks.recommended"), self.metrics.get("block_recommendations")),
            (t("blocks.applied"), self.metrics.get("applied_blocks")),
            (t("blocks.rejected"), self.metrics.get("actually_rejected")),
        ]
        lines.extend(kv_block(surface, counters))
        lines.append("")
        if self.emergency:
            lines.extend(paragraph(surface, t("screening.emergency_off"), role="warn"))
        if self.mode == "DRY_RUN":
            lines.extend(paragraph(surface, t("screening.dry_run_note"), role="muted"))
        else:
            lines.extend(paragraph(surface, t("screening.active_warning"), role="warn"))
        lines.extend(paragraph(surface, t("daemon.android_note"), role="muted"))
        lines.extend(paragraph(surface, t("screening.not_verified"), role="muted"))
        return lines

    # ---------------------------------------------------------------- menu
    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        return [
            MenuItem("status", t("screening.status"),
                     status="ENABLED" if self.enabled else "DISABLED"),
            MenuItem("health", t("screening.health"),
                     enabled=self.daemon_state == "RUNNING"),
            MenuItem("metrics", t("screening.metrics")),
            MenuItem("dry_run", t("screening.set_dry_run"),
                     enabled=self.mode != "DRY_RUN"),
            MenuItem("active", t("screening.set_active"),
                     enabled=not self.emergency),
            MenuItem("enable", t("screening.enable"), enabled=not self.enabled),
            MenuItem("disable", t("screening.disable"), enabled=self.enabled),
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
            return push(ScreeningMetricsScreen(self.ctx))
        if key == "health":
            if self.daemon_state != "RUNNING":
                self.set_message(t("daemon.not_running"), "warn")
                return stay()
            return push(ScreeningHealthScreen(self.ctx))

        if key == "enable":
            result = self.backend.set_screening_enabled(True)
            self._apply(result)
            return stay()
        if key == "disable":
            result = self.backend.set_screening_enabled(False)
            self._apply(result)
            return stay()
        if key == "dry_run":
            result = self.backend.set_screening_mode("dry-run")
            self._apply(result)
            return stay()

        if key == "active":
            if self.emergency:
                self.set_message(t("screening.emergency_off"), "warn")
                return stay()
            # The CLI handler owns the ACTIVE confirmation prompt. Hand it the
            # real terminal so the user answers the original safety question.
            self.set_message("", "info")
            result = self.ctx.run_with_terminal(
                lambda: self.backend.screening_mode_active(),
                notice=t("screening.active_warning"),
            )
            self._apply(result)
            return stay()

        return None

    def _apply(self, result: Any) -> None:
        ok = getattr(result, "ok", False) and (result.data or {}).get("exit_code") == 0
        if ok:
            self.set_message(self.t("common.done"), "ok")
        else:
            detail = ""
            if getattr(result, "ok", False):
                detail = str((result.data or {}).get("output") or "").strip()
            else:
                detail = getattr(result, "error", "")
            self.set_message(
                fmt.truncate(detail.replace("\n", "  "), 200)
                or self.t("error.generic"),
                "warn",
            )
        self.refresh()
        self.rebuild()


__all__ = ["ScreeningHealthScreen", "ScreeningMetricsScreen", "ScreeningScreen"]
