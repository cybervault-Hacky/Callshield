"""Intelligence Center (Phase 8 adaptive intelligence, read-only).

Search, behaviour, timeline, trends, patterns, snapshots and retention. Every
number is scored by :mod:`callshield.adaptive`; the interface never recomputes
a trend, a delta or a pattern on its own.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .. import formatters as fmt
from ..components import bullet_list, Column, kv_block, paragraph, Surface, table
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


def _pattern_rows(patterns: Sequence[Any]) -> List[List[str]]:
    rows: List[List[str]] = []
    for pattern in patterns:
        if isinstance(pattern, dict):
            data = pattern
        else:
            data = {
                "pattern_id": getattr(pattern, "pattern_id", ""),
                "observation_count": getattr(pattern, "observation_count", None),
                "confidence": getattr(pattern, "confidence", None),
                "explanation": getattr(pattern, "explanation", ""),
            }
        rows.append(
            [
                fmt.text_or_placeholder(data.get("pattern_id")),
                fmt.integer(data.get("observation_count")),
                fmt.percent(data.get("confidence")),
                fmt.text_or_placeholder(data.get("explanation")),
            ]
        )
    return rows


class IntelligenceDetailScreen(Screen):
    """Behaviour, trend and pattern summary for one number."""

    name = "intelligence_detail"
    title_key = "intelligence.behavior"

    def __init__(self, ctx: Any, number: str) -> None:
        Screen.__init__(self, ctx)
        self.number = number
        self.snapshot: Dict[str, Any] = {}

    def refresh(self) -> None:
        result = self.backend.intelligence(self.number, include_history=False)
        self.snapshot = result.data or {}
        if not self.snapshot.get("available", True):
            self.set_message(self.t("intelligence.corrupt"), "warn")

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        snapshot = self.snapshot
        if not snapshot:
            return list(empty_state(surface, t("intelligence.no_data")))

        lines = [section_title(surface, t("intelligence.behavior"))]
        lines.extend(
            kv_block(
                surface,
                [
                    (t("common.number"), snapshot.get("number_masked")),
                    (t("scan.field.decision"), snapshot.get("decision")),
                    (t("reputation.trust_state"), snapshot.get("trust_state")),
                    (t("reputation.trust_until"), snapshot.get("trust_expiry")),
                    (t("blocks.recommended"), snapshot.get("recommended")),
                    (t("blocks.applied"), snapshot.get("applied")),
                    (t("blocks.confirmed_at"),
                     fmt.yes_no(snapshot.get("confirmed"))),
                ],
                status_keys=(t("scan.field.decision"),
                             t("reputation.trust_state"), t("blocks.recommended"),
                             t("blocks.applied")),
            )
        )

        lines.append("")
        lines.append(section_title(surface, t("intelligence.current")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("scan.field.current"), snapshot.get("current_score")),
                    (t("common.confidence"),
                     fmt.percent(snapshot.get("reputation_confidence"))),
                ],
            )
        )

        lines.append("")
        lines.append(section_title(surface, t("intelligence.baseline")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("scan.field.baseline"), snapshot.get("baseline_score")),
                ],
            )
        )

        lines.append("")
        lines.append(section_title(surface, t("intelligence.delta")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("scan.field.delta"), fmt.signed(snapshot.get("risk_delta"))),
                    (t("common.confidence"),
                     fmt.signed(snapshot.get("confidence_delta"))),
                ],
            )
        )

        lines.append("")
        lines.append(section_title(surface, t("common.trend")))
        lines.extend(
            kv_block(
                surface,
                [
                    ("BEHAVIORAL", snapshot.get("behavioral_trend")),
                    (t("main.field.blocks"),
                     snapshot.get("recent_block_recommendations")),
                    (t("reports.count"), snapshot.get("recent_user_reports")),
                ],
                status_keys=("BEHAVIORAL",),
            )
        )

        lines.append("")
        lines.append(section_title(surface, t("intelligence.patterns")))
        patterns = snapshot.get("patterns") or []
        lines.extend(
            table(
                surface,
                [
                    Column(t("intelligence.patterns"), min_width=10, priority=3),
                    Column(t("common.count"), align="right", min_width=3,
                           priority=1),
                    Column(t("common.confidence"), align="right", min_width=3,
                           priority=2),
                    Column(t("common.reason"), min_width=10, priority=1),
                ],
                _pattern_rows(patterns),
                empty_message=t("scan.no_patterns"),
            )
        )

        lines.append("")
        lines.append(section_title(surface, t("intelligence.evidence")))
        lines.extend(
            kv_block(
                surface,
                [
                    ("OBSERVATIONS", snapshot.get("recent_observation_count")),
                    ("HIGH RISK", snapshot.get("recent_high_risk_count")),
                ],
            )
        )
        explanations = snapshot.get("explanations") or []
        if explanations:
            lines.append("")
            lines.extend(bullet_list(surface, explanations[:6]))
        lines.append("")
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        lines.extend(paragraph(surface, t("error.no_network"), role="muted"))
        return lines

    def hints(self) -> List[str]:
        return [self.t("nav.back"), self.t("nav.quit")]


class IntelligenceTimelineScreen(ListScreen):
    """Observation timeline for one number."""

    name = "intelligence_timeline"
    title_key = "intelligence.timeline"
    empty_key = "intelligence.no_data"

    def __init__(self, ctx: Any, number: str) -> None:
        self.columns = (
            Column(ctx.t("common.time"), min_width=10, priority=3),
            Column(ctx.t("common.action"), min_width=6, priority=2),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=3),
            Column(ctx.t("blocks.recommended"), min_width=6, priority=2),
            Column(ctx.t("blocks.applied"), min_width=6, priority=1),
            Column(ctx.t("blocks.confirmed_at"), min_width=3, priority=1),
        )
        ListScreen.__init__(self, ctx)
        self.number = number

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.behavior_timeline(self.number, limit=200)
        if not result.ok:
            self.set_message(self.t("intelligence.corrupt"), "warn")
            return []
        rows = []
        for observation in result.data or []:
            rows.append(
                [
                    fmt.timestamp(getattr(observation, "timestamp", None),
                                  short=True),
                    fmt.text_or_placeholder(getattr(observation, "event_type", None)),
                    fmt.integer(getattr(observation, "risk_score", None)),
                    fmt.status_word(getattr(observation, "recommended_action", None)),
                    fmt.status_word(getattr(observation, "applied_action", None)),
                    fmt.yes_no(getattr(observation, "confirmed", False)),
                ]
            )
        return rows

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.t("intelligence.timeline")),
            surface.style(
                "{0}: {1}".format(self.t("common.number"), fmt.masked(self.number)),
                "muted",
            ),
        ]


class IntelligenceSnapshotsScreen(ListScreen):
    """Recently stored intelligence profiles (masked at rest)."""

    name = "intelligence_snapshots"
    title_key = "intelligence.snapshots"
    empty_key = "common.empty"

    def __init__(self, ctx: Any) -> None:
        self.columns = (
            Column(ctx.t("common.number"), min_width=10, priority=3),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=3),
            Column(ctx.t("common.confidence"), align="right", min_width=3,
                   priority=1),
            Column(ctx.t("common.trend"), min_width=6, priority=2),
            Column(ctx.t("scan.field.delta"), align="right", min_width=3,
                   priority=1),
            Column(ctx.t("common.time"), min_width=10, priority=2),
        )
        ListScreen.__init__(self, ctx)

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.recent_intelligence_profiles(limit=200)
        if not result.ok:
            self.set_message(self.t("intelligence.corrupt"), "warn")
            return []
        rows = []
        for row in result.data or []:
            rows.append(
                [
                    fmt.text_or_placeholder(row.get("number_masked")),
                    fmt.integer(row.get("current_score")),
                    fmt.percent(row.get("confidence")),
                    fmt.status_word(row.get("trend")),
                    fmt.signed(row.get("risk_delta")),
                    fmt.timestamp(row.get("updated_at"), short=True),
                ]
            )
        return rows

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.t("intelligence.snapshots")),
            surface.style(self.t("common.masked_note"), "muted"),
        ]


class IntelligenceRetentionScreen(Screen):
    """Retention limits, exactly as configured for the Phase 8 engine."""

    name = "intelligence_retention"
    title_key = "intelligence.retention"

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        cfg = self.ctx.cfg
        rows = [
            (t("intelligence.retention_days"),
             getattr(cfg, "intelligence_history_days", None)),
            (t("intelligence.observation_limit"),
             getattr(cfg, "intelligence_observation_limit", None)),
            (t("intelligence.profile_limit"),
             getattr(cfg, "intelligence_profile_limit", None)),
            ("QUERY LIMIT", getattr(cfg, "intelligence_query_limit", None)),
        ]
        lines = [section_title(surface, t("intelligence.retention"))]
        lines.extend(kv_block(surface, rows))
        lines.append("")
        lines.extend(paragraph(surface, t("settings.data.note"), role="muted"))
        lines.extend(paragraph(surface, t("error.no_network"), role="muted"))
        return lines

    def hints(self) -> List[str]:
        return [self.t("nav.back"), self.t("nav.quit")]


class IntelligenceScreen(MenuScreen):
    """Intelligence Center menu."""

    name = "intelligence"
    title_key = "intelligence.title"

    def __init__(self, ctx: Any) -> None:
        MenuScreen.__init__(self, ctx)
        self.profile_count = 0

    def refresh(self) -> None:
        result = self.backend.recent_intelligence_profiles(limit=200)
        self.profile_count = len(result.data or []) if result.ok else 0

    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        lines: List[str] = []
        lines.extend(
            kv_block(
                surface,
                [
                    (t("intelligence.snapshots"), fmt.integer(self.profile_count)),
                    (t("intelligence.retention_days"),
                     getattr(self.ctx.cfg, "intelligence_history_days", None)),
                ],
            )
        )
        lines.extend(paragraph(surface, t("error.no_network"), role="muted"))
        return lines

    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        return [
            MenuItem("search", t("intelligence.search")),
            MenuItem("behavior", t("intelligence.behavior")),
            MenuItem("timeline", t("intelligence.timeline")),
            MenuItem("trends", t("intelligence.trends")),
            MenuItem("patterns", t("intelligence.patterns")),
            MenuItem("snapshots", t("intelligence.snapshots"),
                     status=fmt.integer(self.profile_count)),
            MenuItem("retention", t("intelligence.retention")),
        ]

    def activate(self, item: MenuItem) -> Optional[Action]:
        t = self.t
        key = item.key

        if key == "snapshots":
            return push(IntelligenceSnapshotsScreen(self.ctx))
        if key == "retention":
            return push(IntelligenceRetentionScreen(self.ctx))

        number = self.ctx.ask(t("prompt.number"))
        if not number:
            self.set_message(t("prompt.empty_input"), "warn")
            return stay()
        check = self.backend.normalize(number)
        if not check.ok:
            self.set_message(t("prompt.invalid_number"), "warn")
            return stay()
        normalized = (check.data or {}).get("normalized") or number
        if key == "timeline":
            return push(IntelligenceTimelineScreen(self.ctx, normalized))
        # search / behavior / trends / patterns all read the same engine
        # snapshot; the detail screen presents each of those sections.
        return push(IntelligenceDetailScreen(self.ctx, normalized))


__all__ = [
    "IntelligenceDetailScreen",
    "IntelligenceRetentionScreen",
    "IntelligenceScreen",
    "IntelligenceSnapshotsScreen",
    "IntelligenceTimelineScreen",
]
