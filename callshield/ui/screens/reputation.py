"""Reputation Center.

Reputation is computed locally by :mod:`callshield.reputation`. Nothing is
fetched from the internet and no external reputation service exists. Trust
changes are executed by the existing ``trust`` / ``untrust`` CLI handlers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .. import formatters as fmt
from ..components import bullet_list, Column, kv_block, paragraph, score_meter, Surface, table
from .base import (
    Action,
    ListScreen,
    MenuItem,
    MenuScreen,
    Screen,
    empty_state,
    push,
    section_title,
    stay,
)


class ReputationDetailScreen(Screen):
    """One reputation profile with signals, reasons and local counters."""

    name = "reputation_detail"
    title_key = "reputation.title"

    def __init__(self, ctx: Any, number: str) -> None:
        Screen.__init__(self, ctx)
        self.number = number
        self.profile: Dict[str, Any] = {}
        self.error = ""

    def title(self) -> str:
        return self.t("reputation.lookup")

    def refresh(self) -> None:
        result = self.backend.reputation(self.number)
        if result.ok:
            self.profile = result.data or {}
            self.error = ""
        else:
            self.profile = {}
            self.error = result.error

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        if not self.profile:
            lines = list(empty_state(surface, t("reputation.no_profile")))
            if self.error:
                lines.append(surface.style(fmt.truncate(self.error, surface.width),
                                           "err"))
            return lines
        profile = self.profile
        if not profile.get("available", True):
            return list(empty_state(surface, t("common.unavailable")))

        lines = [section_title(surface, t("reputation.title"))]
        lines.extend(
            kv_block(
                surface,
                [
                    (t("common.number"), profile.get("number_masked")),
                    (t("common.risk"), profile.get("risk")),
                    (t("common.trend"), profile.get("trend")),
                    (t("reputation.trust_state"),
                     "TRUSTED" if profile.get("trusted") else "UNTRUSTED"),
                    (t("reputation.trust_until"), profile.get("trusted_until")),
                    (t("scan.field.recommendation"), profile.get("recommendation")),
                ],
                status_keys=(t("common.risk"), t("common.trend"),
                             t("reputation.trust_state"),
                             t("scan.field.recommendation")),
            )
        )
        lines.append("")
        lines.append(
            score_meter(surface, profile.get("score"), label=t("common.score"),
                        level=str(profile.get("risk") or ""))
        )
        lines.append(
            score_meter(surface, profile.get("confidence"),
                        label=t("common.confidence"))
        )

        history = profile.get("history") or {}
        if history:
            lines.append("")
            lines.append(section_title(surface, t("reputation.history")))
            lines.extend(
                kv_block(
                    surface,
                    [(key, history.get(key)) for key in sorted(history)],
                )
            )

        signals = profile.get("signals") or []
        lines.append("")
        lines.append(section_title(surface, t("reputation.signals")))
        if signals:
            rows = [
                [
                    str(signal.get("name", "")),
                    fmt.integer(signal.get("score")),
                    fmt.text_or_placeholder(signal.get("reason")),
                ]
                for signal in signals
            ]
            lines.extend(
                table(
                    surface,
                    [
                        Column(t("common.reason"), min_width=10, priority=3),
                        Column(t("common.score"), align="right", min_width=3,
                               priority=3),
                        Column(t("common.notice"), min_width=8, priority=1),
                    ],
                    rows,
                    empty_message=t("scan.no_signals"),
                )
            )
        else:
            lines.extend(empty_state(surface, t("scan.no_signals")))

        reasons = profile.get("reasons") or []
        if reasons:
            lines.append("")
            lines.append(section_title(surface, t("reputation.reasons")))
            lines.extend(bullet_list(surface, reasons[:6]))

        lines.append("")
        lines.extend(paragraph(surface, t("reputation.local_only"), role="muted"))
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        return lines

    def hints(self) -> List[str]:
        return [self.t("nav.back"), self.t("nav.quit")]


class ReputationHistoryScreen(ListScreen):
    """Score transitions recorded for one number."""

    name = "reputation_history"
    title_key = "reputation.history"
    empty_key = "reputation.no_profile"

    def __init__(self, ctx: Any, number: str) -> None:
        self.columns = (
            Column(ctx.t("common.time"), min_width=10, priority=3),
            Column(ctx.t("scan.field.baseline"), align="right", min_width=3,
                   priority=1),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=3),
            Column(ctx.t("common.risk"), min_width=6, priority=2),
            Column(ctx.t("common.reason"), min_width=8, priority=1),
        )
        ListScreen.__init__(self, ctx)
        self.number = number

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.reputation_history(self.number, limit=100)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        rows = []
        for entry in result.data or []:
            rows.append(
                [
                    fmt.timestamp(getattr(entry, "timestamp", None), short=True),
                    fmt.integer(getattr(entry, "old_score", None)),
                    fmt.integer(getattr(entry, "new_score", None)),
                    fmt.status_word(getattr(entry, "risk_after", None)),
                    fmt.text_or_placeholder(getattr(entry, "trigger", None)),
                ]
            )
        return rows

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.t("reputation.history")),
            surface.style(
                "{0}: {1}".format(self.t("common.number"), fmt.masked(self.number)),
                "muted",
            ),
        ]


class RecentProfilesScreen(ListScreen):
    """Recently updated reputation profiles, already masked in storage."""

    name = "reputation_recent"
    title_key = "reputation.recent"
    empty_key = "common.empty"

    def __init__(self, ctx: Any) -> None:
        self.columns = (
            Column(ctx.t("common.number"), min_width=10, priority=3),
            Column(ctx.t("common.risk"), min_width=6, priority=3),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=2),
            Column(ctx.t("common.confidence"), align="right", min_width=3,
                   priority=1),
            Column(ctx.t("common.trend"), min_width=6, priority=1),
            Column(ctx.t("common.time"), min_width=10, priority=2),
        )
        ListScreen.__init__(self, ctx)

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.recent_reputation_profiles(limit=100)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        rows = []
        for row in result.data or []:
            rows.append(
                [
                    fmt.text_or_placeholder(row.get("number_masked")),
                    fmt.status_word(row.get("risk")),
                    fmt.integer(row.get("risk_score")),
                    fmt.percent(row.get("confidence")),
                    fmt.status_word(row.get("trend")),
                    fmt.timestamp(row.get("updated_at"), short=True),
                ]
            )
        return rows

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.t("reputation.recent")),
            surface.style(self.t("common.masked_note"), "muted"),
        ]


class ReputationScreen(MenuScreen):
    """Entry point for local reputation inspection and trust management."""

    name = "reputation"
    title_key = "reputation.title"

    def __init__(self, ctx: Any) -> None:
        MenuScreen.__init__(self, ctx)
        self.profile_count = 0

    def refresh(self) -> None:
        result = self.backend.recent_reputation_profiles(limit=200)
        self.profile_count = len(result.data or []) if result.ok else 0

    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("reputation.title"))]
        lines.extend(
            kv_block(
                surface,
                [
                    (t("reputation.recent"), fmt.integer(self.profile_count)),
                    (t("intelligence.profile_limit"),
                     getattr(self.ctx.cfg, "reputation_profile_limit", None)),
                    (t("intelligence.retention_days"),
                     getattr(self.ctx.cfg, "reputation_history_limit", None)),
                ],
            )
        )
        lines.extend(paragraph(surface, t("reputation.local_only"), role="muted"))
        return lines

    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        return [
            MenuItem("lookup", t("reputation.lookup")),
            MenuItem("recent", t("reputation.recent"),
                     status=fmt.integer(self.profile_count)),
            MenuItem("history", t("reputation.history")),
            MenuItem("trust", t("reputation.trusted")),
        ]

    def activate(self, item: MenuItem) -> Optional[Action]:
        t = self.t
        key = item.key

        if key == "recent":
            return push(RecentProfilesScreen(self.ctx))

        if key in ("lookup", "history"):
            number = self.ctx.ask(t("prompt.number"))
            if not number:
                self.set_message(t("prompt.empty_input"), "warn")
                return stay()
            check = self.backend.normalize(number)
            if not check.ok:
                self.set_message(t("prompt.invalid_number"), "warn")
                return stay()
            normalized = (check.data or {}).get("normalized") or number
            if key == "lookup":
                return push(ReputationDetailScreen(self.ctx, normalized))
            return push(ReputationHistoryScreen(self.ctx, normalized))

        if key == "trust":
            number = self.ctx.ask(t("prompt.number"))
            if not number:
                self.set_message(t("prompt.empty_input"), "warn")
                return stay()
            check = self.backend.normalize(number)
            if not check.ok:
                self.set_message(t("prompt.invalid_number"), "warn")
                return stay()
            normalized = (check.data or {}).get("normalized") or number
            profile = self.backend.reputation(normalized)
            trusted = bool((profile.data or {}).get("trusted")) if profile.ok \
                else False
            question = t("reputation.confirm_untrust") if trusted \
                else t("reputation.confirm_trust")
            if not self.ctx.confirm(question):
                self.set_message(t("common.cancelled"), "info")
                return stay()
            result = self.backend.set_trust(normalized, not trusted)
            ok = result.ok and (result.data or {}).get("exit_code") == 0
            self.set_message(
                t("common.done") if ok else t("error.generic"),
                "ok" if ok else "err",
            )
            return stay()

        return None


__all__ = [
    "RecentProfilesScreen",
    "ReputationDetailScreen",
    "ReputationHistoryScreen",
    "ReputationScreen",
]
