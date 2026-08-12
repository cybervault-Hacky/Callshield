"""Main dashboard.

Three stacked status sections — SYSTEM, THREAT OVERVIEW, INTELLIGENCE — followed
by the QUICK ACTIONS menu and a compact status strip. The layout is deliberately
vertical and quiet: hierarchy comes from spacing and aligned key/value rows,
not from ruling lines. Every value comes from the backend adapter; nothing here
is invented, and a value that cannot be read is shown as ``--`` rather than as
a zero.
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

from .. import formatters as fmt
from ..components import Surface, kv_block, paragraph, section_title, status_bar
from .base import MenuItem, MenuScreen, home, push, quit_app, stay

#: Menu key -> screen factory attribute on the registry.
QUICK_ACTIONS: Tuple[Tuple[str, str], ...] = (
    ("scan", "menu.scan"),
    ("monitor", "menu.monitor"),
    ("daemon", "menu.daemon"),
    ("screening", "menu.screening"),
    ("policy", "menu.policy"),
    ("reputation", "menu.reputation"),
    ("intelligence", "menu.intelligence"),
    ("number_intel", "menu.number_intel"),
    ("blocks", "menu.blocks"),
    ("reports", "menu.reports"),
    ("history", "menu.history"),
    ("diagnostics", "menu.diagnostics"),
    ("settings", "menu.settings"),
    ("about", "menu.about"),
    ("exit", "menu.exit"),
)


class DashboardScreen(MenuScreen):
    """Landing screen: live system posture plus the quick action menu."""

    name = "dashboard"
    title_key = "main.title"
    menu_title_key = "main.section.actions"
    live = True

    def __init__(self, ctx: Any) -> None:
        MenuScreen.__init__(self, ctx)
        self.system: Dict[str, Any] = {}
        self.threat: Dict[str, Any] = {}
        self.intel: Dict[str, Any] = {}
        self.daemon_state = "UNKNOWN"
        self.metrics_source = ""

    # ------------------------------------------------------------ data load
    def refresh(self) -> None:
        backend = self.backend
        state, pid = backend.daemon_state()
        self.daemon_state = state

        policy = backend.policy_snapshot()
        metrics = backend.daemon_metrics()
        self.metrics_source = metrics.source if metrics.ok else ""
        data = metrics.data if metrics.ok else {}

        events = backend.event_metrics()
        event_data = events.data if events.ok else {}

        screening = backend.screening_metrics()
        screening_data = screening.data if screening.ok else {}

        profiles = backend.recent_reputation_profiles(200)
        snapshots = backend.recent_intelligence_profiles(200)

        screening_word = "DISABLED"
        if policy.get("emergency_off"):
            screening_word = "EMERGENCY OFF"
        elif policy.get("enabled"):
            screening_word = str(policy.get("mode") or "DRY_RUN")

        self.system = {
            "daemon": state,
            "engine": "READY",
            "database": "READY" if events.ok else "ERROR",
            "ipc": "READY" if state == "RUNNING" else "OFFLINE",
            "policy": policy.get("current"),
            "pid": pid,
            "uptime": data.get("uptime_human") or data.get("uptime_seconds"),
            "queue": self._queue_text(data),
            "screening": screening_word,
        }

        self.threat = {
            "events": event_data.get("total"),
            "high_risk": event_data.get("high_risk"),
            "recommended": screening_data.get("screening_block_recommended"),
            "rejected": screening_data.get("actually_rejected"),
            "blocks": event_data.get("block_recommendations"),
        }

        profile_rows = profiles.data if profiles.ok else []
        snapshot_rows = snapshots.data if snapshots.ok else []
        trusted = 0
        for row in profile_rows:
            try:
                if str(row.get("trust_state", "")).upper() == "TRUSTED":
                    trusted += 1
            except AttributeError:  # pragma: no cover - unexpected row shape
                continue
        self.intel = {
            "profiles": len(profile_rows) if profiles.ok else None,
            "observations": len(snapshot_rows) if snapshots.ok else None,
            "tracked": self._tracked(snapshot_rows),
            "trusted": trusted if profiles.ok else None,
            "trend": self._dominant_trend(snapshot_rows),
        }

    @staticmethod
    def _queue_text(data: Dict[str, Any]) -> Any:
        size = data.get("queue_size")
        maximum = data.get("queue_max")
        if size is None and maximum is None:
            return None
        return "{0}/{1}".format(fmt.integer(size), fmt.integer(maximum))

    @staticmethod
    def _tracked(rows: Sequence[Any]) -> Any:
        try:
            return len({row.get("number_masked") for row in rows})
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _dominant_trend(rows: Sequence[Any]) -> Any:
        counts: Dict[str, int] = {}
        for row in rows:
            try:
                trend = str(row.get("trend") or "").upper()
            except Exception:  # noqa: BLE001
                continue
            if trend:
                counts[trend] = counts.get(trend, 0) + 1
        if not counts:
            return None
        return max(counts.items(), key=lambda item: item[1])[0]

    # -------------------------------------------------------------- render
    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        lines: List[str] = []

        lines.append(section_title(surface, t("main.section.system")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("main.field.daemon"), self.system.get("daemon")),
                    (t("main.field.engine"), self.system.get("engine")),
                    (t("main.field.database"), self.system.get("database")),
                    (t("main.field.ipc"), self.system.get("ipc")),
                    (t("main.field.policy"), self.system.get("policy")),
                ],
                status_keys=(
                    t("main.field.daemon"),
                    t("main.field.engine"),
                    t("main.field.database"),
                    t("main.field.ipc"),
                    t("main.field.policy"),
                ),
            )
        )

        lines.append("")
        lines.append(section_title(surface, t("main.section.threat")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("main.field.events"), self.threat.get("events")),
                    (t("main.field.high_risk"), self.threat.get("high_risk")),
                    (t("main.field.recommended"), self.threat.get("recommended")),
                    (t("main.field.rejected"), self.threat.get("rejected")),
                ],
            )
        )

        lines.append("")
        lines.append(section_title(surface, t("main.section.intelligence")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("main.field.profiles"), self.intel.get("profiles")),
                    (t("main.field.observations"), self.intel.get("observations")),
                    (t("common.trend"), self.intel.get("trend")),
                ],
                status_keys=(t("common.trend"),),
            )
        )

        if self.daemon_state != "RUNNING":
            lines.append("")
            lines.extend(
                paragraph(surface, self.t("main.daemon_offline_hint"), role="warn")
            )
        if self.metrics_source == "offline":
            lines.extend(
                paragraph(surface, self.t("error.daemon_unavailable"), role="muted")
            )
        lines.extend(
            paragraph(surface, self.t("main.no_android"), role="muted")
        )
        return lines

    def outro(self, surface: Surface) -> List[str]:
        return status_bar(
            surface,
            [
                (self.t("main.field.daemon"), self.daemon_state),
                (self.t("main.field.policy"), self.system.get("policy") or "UNKNOWN"),
                (self.t("main.field.screening"),
                 self.system.get("screening") or "UNKNOWN"),
            ],
        )

    # ---------------------------------------------------------------- menu
    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        items: List[MenuItem] = []
        if self.daemon_state != "RUNNING":
            items.append(
                MenuItem("start_daemon", t("main.action.start_daemon"),
                         status="OFFLINE")
            )
        for key, label_key in QUICK_ACTIONS:
            items.append(MenuItem(key, t(label_key)))
        return items

    def activate(self, item: MenuItem):
        if item.key == "exit":
            return quit_app()
        if item.key == "start_daemon":
            self.set_message(self.t("daemon.starting"), "info")
            result = self.backend.start_daemon()
            if result.ok and (result.data or {}).get("exit_code") == 0:
                self.set_message(self.t("common.done"), "ok")
            else:
                detail = (result.data or {}).get("output", "") if result.ok \
                    else result.error
                self.set_message(fmt.truncate(detail.strip().replace("\n", " "),
                                              160) or self.t("error.generic"), "err")
            self.refresh()
            self.rebuild()
            return stay()
        screen = self.ctx.make_screen(item.key)
        if screen is None:
            self.set_message(self.t("error.unsupported"), "warn")
            return stay()
        return push(screen)

    def handle(self, key: str):
        if key in ("r", "R"):
            self.refresh()
            self.rebuild()
            self.set_message(self.t("common.done"), "ok")
            return stay()
        if key in ("h", "H"):
            return home()
        return MenuScreen.handle(self, key)

    def hints(self) -> List[str]:
        return [
            self.t("nav.hint"),
            self.t("nav.number_hint"),
            "r " + self.t("nav.refresh"),
        ]


__all__ = ["DashboardScreen", "QUICK_ACTIONS"]
