"""NUMBER INTELLIGENCE screen — local-only, no identity invention."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .. import formatters as fmt
from ..components import (
    Column,
    Surface,
    bullet_list,
    card,
    kv,
    kv_block,
    paragraph,
    table,
)
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


def _value(field: Any) -> Any:
    if isinstance(field, dict):
        return field.get("value")
    return field


def _avail(field: Any) -> str:
    if isinstance(field, dict):
        return str(field.get("availability") or "UNKNOWN")
    return "AVAILABLE"


def _display(field: Any) -> str:
    value = _value(field)
    if value in (None, "", []):
        return str(_avail(field) or "NOT AVAILABLE").replace("_", " ")
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


class NumberScanScreen(Screen):
    name = "number_scan"

    def __init__(self, ctx: Any, number: str) -> None:
        Screen.__init__(self, ctx)
        self.number = number
        self.profile: Dict[str, Any] = {}
        self.error = ""

    def title(self) -> str:
        return self.t("number_intel.scan")

    def refresh(self) -> None:
        result = self.backend.number_profile(self.number)
        if not result.ok:
            self.profile = {}
            self.error = result.error
            self.set_message(self.error or self.t("error.generic"), "err")
            return
        self.error = ""
        self.clear_message()
        self.profile = result.data or {}
        if not self.profile.get("valid", True):
            self.set_message(self.profile.get("error") or self.t("error.generic"), "err")

    def on_enter(self) -> None:
        self.refresh()

    def _card_rows(self, surface: Surface, rows: Sequence[tuple]) -> List[str]:
        card_width = max(20, min(surface.width, 64))
        inner_width = max(8, card_width - 4)

        def row(label: str, value: Any) -> str:
            return kv(surface, label, value, width=inner_width, label_width=16, status=True)

        inner = [row(label, value) for label, value in rows]
        return card(surface, inner, width=card_width)

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        if not self.profile:
            return [surface.style(self.error or t("error.generic"), "err")]
        p = self.profile
        lines: List[str] = [section_title(surface, t("number_intel.title"))]
        lines.append("")
        lines.append(section_title(surface, t("number_intel.section.number")))
        lines.append(surface.style(_display(p.get("masked_number")), "bold"))
        lines.append("")
        lines.append(section_title(surface, t("number_intel.section.identity")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("number_intel.field.contact"), _display(p.get("local_contact_status"))),
                    (t("number_intel.field.name"), _display(p.get("contact_name"))),
                    (t("number_intel.field.age"), _display(p.get("age"))),
                    (t("number_intel.field.identity"), _display(p.get("owner_identity"))),
                ],
                status_keys=(
                    t("number_intel.field.contact"),
                    t("number_intel.field.identity"),
                ),
            )
        )
        lines.append("")
        lines.append(section_title(surface, t("number_intel.section.threat")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("common.risk"), "{0}/100".format(_display(p.get("reputation_score")))),
                    (t("common.confidence"), "{0}%".format(_display(p.get("reputation_confidence")))),
                    (t("scan.field.risk_level"), _display(p.get("risk_level"))),
                    (t("common.verdict"), _display(p.get("verdict"))),
                    (t("scan.field.recommendation"), _display(p.get("recommendation"))),
                ],
                status_keys=(
                    t("scan.field.risk_level"),
                    t("common.verdict"),
                    t("scan.field.recommendation"),
                ),
            )
        )
        lines.append("")
        lines.append(section_title(surface, t("number_intel.section.reputation")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("reports.count"), _display(p.get("reports"))),
                    (t("number_intel.field.calls"), _display(p.get("calls_observed"))),
                    (t("common.trend"), _display(p.get("behavioral_trend"))),
                    (t("reputation.trust_state"), _display(p.get("trust_state"))),
                ],
                status_keys=(t("common.trend"), t("reputation.trust_state")),
            )
        )
        lines.append("")
        lines.append(section_title(surface, t("number_intel.section.behavior")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("scan.field.first_seen"), _display(p.get("first_seen"))),
                    (t("scan.field.last_seen"), _display(p.get("last_seen"))),
                    (t("number_intel.field.blocks"), _display(p.get("historical_block_recommendations"))),
                ],
            )
        )
        lines.append("")
        lines.append(section_title(surface, t("number_intel.section.evidence")))
        evidence = _value(p.get("measured_evidence"))
        if _avail(p.get("measured_evidence")) == "AVAILABLE" and evidence:
            lines.extend(bullet_list(surface, [str(item) for item in evidence[:8]]))
        else:
            lines.extend(empty_state(surface, t("number_intel.no_evidence")))
        lines.append("")
        lines.append(section_title(surface, t("number_intel.section.privacy")))
        lines.extend(
            kv_block(
                surface,
                [
                    (t("number_intel.field.source"), "LOCAL ONLY"),
                    (t("number_intel.field.network"), "NONE"),
                    (t("number_intel.field.identity"), _display(p.get("owner_identity"))),
                    (t("scan.field.country"), _display(p.get("country"))),
                ],
            )
        )
        lines.append("")
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        return lines


class SavedContactsScreen(ListScreen):
    name = "saved_contacts"
    empty_key = "number_intel.no_contacts"

    def __init__(self, ctx: Any) -> None:
        ListScreen.__init__(self, ctx)
        self.columns = [
            Column(ctx.t("common.number"), min_width=10, priority=3),
            Column(ctx.t("number_intel.field.name"), min_width=8, priority=2),
            Column(ctx.t("number_intel.field.source"), min_width=8, priority=1),
        ]

    def title(self) -> str:
        return self.t("number_intel.saved")

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.contact_list(limit=200)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        rows = []
        for row in result.data or []:
            rows.append(
                [
                    row.get("number_masked"),
                    row.get("display_name"),
                    row.get("source") or "Local Contacts",
                ]
            )
        return rows


class ContactScanSummaryScreen(Screen):
    name = "contact_scan_summary"

    def __init__(self, ctx: Any) -> None:
        Screen.__init__(self, ctx)
        self.summary: Dict[str, Any] = {}
        self.error = ""

    def title(self) -> str:
        return self.t("number_intel.imported")

    def refresh(self) -> None:
        result = self.backend.contact_scan()
        if not result.ok:
            self.summary = {}
            self.error = result.error
            self.set_message(self.error, "err")
            return
        self.summary = result.data or {}

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        if not self.summary:
            return [surface.style(self.error or t("error.generic"), "err")]
        s = self.summary
        lines = [section_title(surface, t("number_intel.scan_summary"))]
        lines.extend(
            kv_block(
                surface,
                [
                    (t("number_intel.stat.total"), s.get("total")),
                    (t("number_intel.stat.valid"), s.get("valid")),
                    (t("number_intel.stat.invalid"), s.get("invalid")),
                    (t("number_intel.stat.known"), s.get("known_contacts")),
                    (t("number_intel.stat.unknown_numbers"), s.get("unknown_numbers")),
                    (t("number_intel.stat.high"), s.get("high_risk")),
                    (t("number_intel.stat.medium"), s.get("medium_risk")),
                    (t("number_intel.stat.low"), s.get("low_risk")),
                    (t("number_intel.stat.unknown"), s.get("unknown")),
                    (t("number_intel.stat.trusted"), s.get("trusted")),
                ],
            )
        )
        lines.append("")
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        return lines


class NumberCompareScreen(Screen):
    name = "number_compare"

    def __init__(self, ctx: Any, first: str, second: str) -> None:
        Screen.__init__(self, ctx)
        self.first = first
        self.second = second
        self.left: Dict[str, Any] = {}
        self.right: Dict[str, Any] = {}

    def title(self) -> str:
        return self.t("number_intel.compare")

    def refresh(self) -> None:
        left = self.backend.number_profile(self.first)
        right = self.backend.number_profile(self.second)
        self.left = left.data if left.ok else {}
        self.right = right.data if right.ok else {}

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("scan.compare.header"))]
        rows = [
            [t("scan.field.masked"),
             _display(self.left.get("masked_number")),
             _display(self.right.get("masked_number"))],
            [t("common.risk"),
             _display(self.left.get("reputation_score")),
             _display(self.right.get("reputation_score"))],
            [t("common.verdict"),
             _display(self.left.get("verdict")),
             _display(self.right.get("verdict"))],
            [t("number_intel.field.identity"),
             _display(self.left.get("owner_identity")),
             _display(self.right.get("owner_identity"))],
        ]
        lines.extend(
            table(
                surface,
                [
                    Column(t("common.result"), min_width=8, priority=3),
                    Column("A", min_width=6, priority=2),
                    Column("B", min_width=6, priority=2),
                ],
                rows,
            )
        )
        lines.append("")
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        return lines


class NumberExportScreen(Screen):
    name = "number_export"

    def title(self) -> str:
        return self.t("number_intel.export")

    def body(self, surface: Surface) -> List[str]:
        return paragraph(
            surface,
            self.t("number_intel.export_note"),
            role="muted",
        )


class NumberIntelligenceScreen(MenuScreen):
    name = "number_intel"
    title_key = "number_intel.title"

    def intro(self, surface: Surface) -> List[str]:
        status = self.backend.contact_status()
        count = status.get("count") if status.ok else None
        return [
            surface.style(self.t("number_intel.title"), "title"),
            surface.style(
                "{0}: {1}".format(self.t("number_intel.imported_count"), fmt.integer(count)),
                "muted",
            ),
        ]

    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        return [
            MenuItem("scan", t("number_intel.scan")),
            MenuItem("saved", t("number_intel.saved")),
            MenuItem("imported", t("number_intel.imported")),
            MenuItem("history", t("number_intel.history")),
            MenuItem("compare", t("number_intel.compare")),
            MenuItem("export", t("number_intel.export")),
        ]

    def activate(self, item: MenuItem) -> Optional[Action]:
        t = self.t
        if item.key == "saved":
            return push(SavedContactsScreen(self.ctx))
        if item.key == "imported":
            return push(ContactScanSummaryScreen(self.ctx))
        if item.key == "history":
            from .scan import ScanHistoryScreen

            return push(ScanHistoryScreen(self.ctx))
        if item.key == "export":
            return push(NumberExportScreen(self.ctx))
        if item.key == "compare":
            first = self.ctx.ask(t("scan.compare.first"))
            if not first:
                self.set_message(t("common.cancelled"), "info")
                return stay()
            second = self.ctx.ask(t("scan.compare.second"))
            if not second:
                self.set_message(t("common.cancelled"), "info")
                return stay()
            return push(NumberCompareScreen(self.ctx, first, second))
        number = self.ctx.ask(t("prompt.number"))
        if not number:
            self.set_message(t("prompt.empty_input"), "warn")
            return stay()
        return push(NumberScanScreen(self.ctx, number))


__all__ = [
    "ContactScanSummaryScreen",
    "NumberCompareScreen",
    "NumberExportScreen",
    "NumberIntelligenceScreen",
    "NumberScanScreen",
    "SavedContactsScreen",
]
