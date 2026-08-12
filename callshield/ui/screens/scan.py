"""Scan Center.

Basic Scan, Advanced Scan, Scan History and Compare Results. All analysis is
performed by the existing detection, reputation, adaptive and policy engines;
this module only arranges their output.

Nothing that CALLSHIELD cannot know is ever displayed: no caller name, no
location, no carrier, no call duration, no audio analysis, no contact data and
no external reputation service.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .. import formatters as fmt
from ..components import bullet_list, Column, kv_block, paragraph, score_meter, Surface, table
from .base import (
    Action,
    DetailScreen,
    ListScreen,
    MenuItem,
    MenuScreen,
    Screen,
    empty_state,
    push,
    section_title,
    stay,
)


def _thresholds(cfg: Any) -> str:
    return "risk >= {0}   high risk >= {1}".format(
        getattr(cfg, "risk_threshold", "--"),
        getattr(cfg, "high_risk_threshold", "--"),
    )


def basic_sections(ctx: Any, surface: Surface, analysis: Any) -> List[str]:
    """The compact result block shared by Basic Scan and the advanced header."""

    t = ctx.t
    lines: List[str] = []
    lines.append(section_title(surface, t("scan.section.identity")))
    lines.extend(
        kv_block(
            surface,
            [
                (t("scan.field.masked"), fmt.masked(analysis.normalized_number)),
                (t("scan.field.risk_level"), analysis.risk_level),
                (t("common.verdict"), analysis.verdict),
                (t("scan.field.recommendation"), analysis.recommended_action),
            ],
            status_keys=(
                t("scan.field.risk_level"),
                t("common.verdict"),
                t("scan.field.recommendation"),
            ),
        )
    )
    lines.append("")
    lines.append(
        score_meter(surface, analysis.risk_score, label=t("common.score"),
                    level=analysis.risk_level)
    )
    lines.append(
        score_meter(surface, analysis.confidence, label=t("common.confidence"))
    )
    if analysis.reason:
        lines.append("")
        lines.append(surface.style(fmt.truncate(analysis.reason, surface.width),
                                   "value"))
    return lines


class ScanResultScreen(Screen):
    """Basic scan result: verdict, score, confidence, signals, list status."""

    name = "scan_result"

    def __init__(self, ctx: Any, number: str) -> None:
        Screen.__init__(self, ctx)
        self.number = number
        self.analysis: Any = None
        self.error = ""
        self.history_count: Optional[int] = None
        self.list_status = ""

    def title(self) -> str:
        return self.t("scan.basic")

    def refresh(self) -> None:
        result = self.backend.scan(self.number)
        if not result.ok:
            self.analysis = None
            self.error = result.error
            # Surface the engine's own wording (e.g. "Invalid phone number:
            # ...") as a levelled notice so the failure is labelled ERROR and
            # not signalled by colour alone.
            self.set_message(self.error or self.t("error.generic"), "err")
            return
        self.error = ""
        self.clear_message()
        self.analysis = result.data
        normalized = self.analysis.normalized_number
        count = self.backend.number_history_count(normalized)
        self.history_count = count.data if count.ok else None
        self.list_status = self._list_status(normalized)

    def _list_status(self, normalized: str) -> str:
        for name, word in (("blacklist", "BLACKLISTED"), ("whitelist", "WHITELISTED")):
            entries = self.backend.list_numbers(name, limit=500)
            if entries.ok:
                for entry in entries.data or []:
                    if entry.get("number") == normalized:
                        return word
        return "NONE"

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        if self.analysis is None:
            return [surface.style(self.error or t("error.generic"), "err")]

        lines = basic_sections(self.ctx, surface, self.analysis)
        lines.append("")
        lines.append(section_title(surface, t("scan.section.signals")))
        signals = list(getattr(self.analysis, "signals", None) or [])
        if signals:
            rows = [
                [
                    str(signal.get("name", "")),
                    fmt.integer(signal.get("score")),
                    str(signal.get("reason", "")),
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
                        Column(t("common.notice"), min_width=10, priority=1),
                    ],
                    rows,
                    empty_message=t("scan.no_signals"),
                )
            )
        else:
            lines.extend(empty_state(surface, t("scan.no_signals")))

        lines.append("")
        lines.extend(
            kv_block(
                surface,
                [
                    (t("scan.field.list"), self.list_status),
                    (t("scan.field.events"), self.history_count),
                    (t("scan.field.threshold"), _thresholds(self.ctx.cfg)),
                ],
            )
        )
        lines.append("")
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        return lines

    def hints(self) -> List[str]:
        return [
            "a " + self.t("scan.advanced"),
            "h " + self.t("scan.history"),
            self.t("nav.hint"),
        ]

    def handle(self, key: str) -> Optional[Action]:
        if self.analysis is None:
            return None
        if key in ("a", "A"):
            return push(AdvancedScanScreen(self.ctx, self.analysis.normalized_number))
        if key in ("h", "H"):
            return push(ScanHistoryScreen(self.ctx, self.analysis.normalized_number))
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return None


class AdvancedScanScreen(Screen):
    """Ten-section deep analysis of one number."""

    name = "advanced_scan"

    def __init__(self, ctx: Any, number: str) -> None:
        Screen.__init__(self, ctx)
        self.number = number
        self.analysis: Any = None
        self.normalized: Dict[str, Any] = {}
        self.reputation: Dict[str, Any] = {}
        self.snapshot: Dict[str, Any] = {}
        self.decision: Any = None
        self.history: List[Any] = []
        self.history_count: Optional[int] = None
        self.list_status = "NONE"
        self.errors: List[str] = []

    def title(self) -> str:
        return self.t("scan.advanced")

    # ------------------------------------------------------------ data load
    def refresh(self) -> None:
        self.errors = []
        backend = self.backend

        normalized = backend.normalize(self.number)
        if normalized.ok:
            self.normalized = normalized.data or {}
        else:
            self.errors.append(normalized.error)
            self.normalized = {}

        target = self.normalized.get("normalized") or self.number

        analysis = backend.scan(target)
        if analysis.ok:
            self.analysis = analysis.data
        else:
            self.analysis = None
            self.errors.append(analysis.error)

        reputation = backend.reputation(target, persist=True)
        self.reputation = reputation.data if reputation.ok else {}
        if not reputation.ok:
            self.errors.append(reputation.error)

        snapshot = backend.intelligence(target)
        self.snapshot = snapshot.data if snapshot.ok else {}

        if self.analysis is not None:
            decision = backend.policy_simulate(
                int(getattr(self.analysis, "risk_score", 0) or 0),
                int(getattr(self.analysis, "confidence", 0) or 0),
                mode=getattr(self.ctx.cfg, "screening_mode", "DRY_RUN"),
            )
            self.decision = decision.data if decision.ok else None
            if not decision.ok:
                self.errors.append(decision.error)

        history = backend.number_history(target, limit=10)
        self.history = history.data if history.ok else []
        count = backend.number_history_count(target)
        self.history_count = count.data if count.ok else None
        self.list_status = self._list_status(target)

    def _list_status(self, normalized: str) -> str:
        for name, word in (("blacklist", "BLACKLISTED"), ("whitelist", "WHITELISTED")):
            entries = self.backend.list_numbers(name, limit=500)
            if entries.ok:
                for entry in entries.data or []:
                    if entry.get("number") == normalized:
                        return word
        return "NONE"

    def on_enter(self) -> None:
        self.refresh()

    # ---------------------------------------------------------------- parts
    def _identity(self, surface: Surface) -> List[str]:
        t = self.t
        normalized = self.normalized.get("normalized")
        rows = [
            (t("scan.field.input"), fmt.masked(self.number)),
            (t("scan.field.normalized"), fmt.masked(normalized)),
            (t("scan.field.masked"), fmt.masked(normalized)),
            (t("scan.field.country"), self.normalized.get("country_code")),
            (t("scan.field.list"), self.list_status),
        ]
        out = [section_title(surface, t("scan.section.identity"))]
        out.extend(kv_block(surface, rows))
        return out

    def _reputation(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("scan.section.reputation"))]
        if not self.reputation:
            out.extend(empty_state(surface, t("reputation.no_profile")))
            return out
        if not self.reputation.get("available", True):
            out.extend(empty_state(surface, t("common.unavailable")))
            return out
        out.extend(
            kv_block(
                surface,
                [
                    (t("common.risk"), self.reputation.get("risk")),
                    (t("common.score"), self.reputation.get("score")),
                    (t("common.confidence"),
                     fmt.percent(self.reputation.get("confidence"))),
                    (t("scan.field.recommendation"),
                     self.reputation.get("recommendation")),
                ],
                status_keys=(t("common.risk"), t("scan.field.recommendation")),
            )
        )
        reasons = self.reputation.get("reasons") or []
        if reasons:
            out.append("")
            out.extend(bullet_list(surface, reasons[:5]))
        out.extend(paragraph(surface, t("reputation.local_only"), role="muted"))
        return out

    def _signals(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("scan.section.signals"))]
        signals = list(getattr(self.analysis, "signals", None) or [])
        if not signals:
            out.extend(empty_state(surface, t("scan.no_signals")))
            return out
        rows = [
            [
                str(signal.get("name", "")),
                fmt.integer(signal.get("score")),
                str(signal.get("reason", "")),
            ]
            for signal in signals
        ]
        out.extend(
            table(
                surface,
                [
                    Column(t("common.reason"), min_width=10, priority=3),
                    Column(t("common.score"), align="right", min_width=3, priority=3),
                    Column(t("common.notice"), min_width=8, priority=1),
                ],
                rows,
                empty_message=t("scan.no_signals"),
            )
        )
        return out

    def _confidence(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("scan.section.confidence"))]
        out.append(
            score_meter(surface, getattr(self.analysis, "risk_score", None),
                        label=t("scan.field.risk_score"),
                        level=getattr(self.analysis, "risk_level", ""))
        )
        out.append(
            score_meter(surface, getattr(self.analysis, "confidence", None),
                        label=t("common.confidence"))
        )
        out.extend(
            kv_block(
                surface,
                [
                    (t("common.verdict"), getattr(self.analysis, "verdict", None)),
                    (t("scan.field.recommendation"),
                     getattr(self.analysis, "recommended_action", None)),
                ],
                status_keys=(t("common.verdict"), t("scan.field.recommendation")),
            )
        )
        return out

    def _behavior(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("scan.section.behavior"))]
        if not self.snapshot:
            out.extend(empty_state(surface, t("intelligence.no_data")))
            return out
        if not self.snapshot.get("available", True):
            out.extend(empty_state(surface, t("intelligence.corrupt")))
            return out
        out.extend(
            kv_block(
                surface,
                [
                    (t("scan.field.decision"), self.snapshot.get("decision")),
                    (t("scan.field.baseline"), self.snapshot.get("baseline_score")),
                    (t("scan.field.current"), self.snapshot.get("current_score")),
                    (t("scan.field.delta"), fmt.signed(self.snapshot.get("risk_delta"))),
                    ("OBSERVED", self.snapshot.get("observed")),
                    ("RECOMMENDED", self.snapshot.get("recommended")),
                    ("APPLIED", self.snapshot.get("applied")),
                ],
                status_keys=("RECOMMENDED", "APPLIED"),
            )
        )
        patterns = self.snapshot.get("patterns") or []
        out.append("")
        out.append(surface.style(t("scan.field.patterns"), "label"))
        if patterns:
            out.extend(bullet_list(surface, [self._pattern_text(p) for p in patterns]))
        else:
            out.extend(empty_state(surface, t("scan.no_patterns")))
        return out

    @staticmethod
    def _pattern_text(pattern: Any) -> str:
        if isinstance(pattern, dict):
            return "{0}: {1}".format(
                pattern.get("pattern_id", "pattern"),
                pattern.get("explanation", ""),
            )
        return "{0}: {1}".format(
            getattr(pattern, "pattern_id", "pattern"),
            getattr(pattern, "explanation", ""),
        )

    def _trend(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("scan.section.trend"))]
        out.extend(
            kv_block(
                surface,
                [
                    (t("common.trend"), self.reputation.get("trend")),
                    ("BEHAVIORAL", self.snapshot.get("behavioral_trend")),
                    (t("scan.field.delta"),
                     fmt.signed(self.snapshot.get("confidence_delta"))),
                ],
                status_keys=(t("common.trend"), "BEHAVIORAL"),
            )
        )
        return out

    def _trust(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("scan.section.trust"))]
        trusted = self.reputation.get("trusted")
        out.extend(
            kv_block(
                surface,
                [
                    (t("reputation.trust_state"),
                     self.snapshot.get("trust_state")
                     or ("TRUSTED" if trusted else "UNTRUSTED")),
                    (t("reputation.trust_until"),
                     self.reputation.get("trusted_until")
                     or self.snapshot.get("trust_expiry")),
                ],
                status_keys=(t("reputation.trust_state"),),
            )
        )
        return out

    def _policy(self, surface: Surface) -> List[str]:
        t = self.t
        snapshot = self.backend.policy_snapshot()
        out = [section_title(surface, t("scan.section.policy"))]
        rows = [
            (t("policy.current"), snapshot.get("current")),
            (t("common.mode"), snapshot.get("mode")),
            (t("policy.emergency"),
             "ENGAGED" if snapshot.get("emergency_off") else "CLEAR"),
        ]
        if self.decision is not None:
            rows.extend(
                [
                    (t("scan.field.decision"),
                     getattr(self.decision, "recommended_action", None)),
                    (t("blocks.applied"), getattr(self.decision, "applied_action", None)),
                    (t("policy.block_threshold"),
                     getattr(self.decision, "threshold", None)),
                    (t("policy.confidence_threshold"),
                     getattr(self.decision, "confidence_threshold", None)),
                ]
            )
        out.extend(
            kv_block(surface, rows,
                     status_keys=(t("scan.field.decision"), t("blocks.applied")))
        )
        out.extend(paragraph(surface, t("scan.policy_note"), role="muted"))
        return out

    def _screening(self, surface: Surface) -> List[str]:
        t = self.t
        snapshot = self.backend.policy_snapshot()
        state, _pid = self.backend.daemon_state()
        out = [section_title(surface, t("scan.section.screening"))]
        out.extend(
            kv_block(
                surface,
                [
                    (t("screening.status"),
                     "ENABLED" if snapshot.get("enabled") else "DISABLED"),
                    (t("common.mode"), snapshot.get("mode")),
                    (t("main.field.daemon"), state),
                    ("Android", "NOT VERIFIED"),
                ],
                status_keys=(t("screening.status"), t("common.mode"),
                             t("main.field.daemon"), "Android"),
            )
        )
        out.extend(paragraph(surface, t("screening.not_verified"), role="muted"))
        return out

    def _history(self, surface: Surface) -> List[str]:
        t = self.t
        out = [section_title(surface, t("scan.section.history"))]
        if not self.history:
            out.extend(empty_state(surface, t("scan.no_history")))
            return out
        rows = [
            [
                fmt.timestamp(row.get("timestamp"), short=True),
                fmt.integer(row.get("risk_score")),
                fmt.status_word(row.get("verdict")),
                fmt.status_word(row.get("action")),
            ]
            for row in self.history
        ]
        out.extend(
            table(
                surface,
                [
                    Column(t("common.time"), min_width=10, priority=3),
                    Column(t("common.score"), align="right", min_width=3, priority=3),
                    Column(t("common.verdict"), min_width=6, priority=2),
                    Column(t("common.action"), min_width=6, priority=1),
                ],
                rows,
                empty_message=t("scan.no_history"),
            )
        )
        out.append(
            surface.style(
                "{0}: {1}".format(t("scan.field.events"),
                                  fmt.integer(self.history_count)),
                "muted",
            )
        )
        return out

    # --------------------------------------------------------------- render
    def body(self, surface: Surface) -> List[str]:
        if self.analysis is None:
            message = self.errors[0] if self.errors else self.t("error.generic")
            return [surface.style(message, "err")]

        blocks = [
            self._identity,
            self._reputation,
            self._signals,
            self._confidence,
            self._behavior,
            self._trend,
            self._trust,
            self._policy,
            self._screening,
            self._history,
        ]
        lines: List[str] = []
        for index, block in enumerate(blocks):
            if index:
                lines.append("")
            try:
                lines.extend(block(surface))
            except Exception as exc:  # noqa: BLE001 - one bad section, not a crash
                lines.append(surface.style(
                    "{0}: {1}".format(self.t("error.corrupt_data"), exc), "err"))
        lines.append("")
        lines.extend(paragraph(surface, self.t("common.masked_note"), role="muted"))
        return lines

    def hints(self) -> List[str]:
        return ["r " + self.t("nav.refresh"), self.t("nav.hint")]

    def handle(self, key: str) -> Optional[Action]:
        if key in ("r", "R"):
            self.refresh()
            return stay()
        return None


class ScanHistoryScreen(ListScreen):
    """Bounded scan history, either for one number or across all numbers."""

    name = "scan_history"
    empty_key = "scan.no_history"

    def __init__(self, ctx: Any, number: str = "") -> None:
        ListScreen.__init__(self, ctx)
        self.number = number
        self.columns = [
            Column(ctx.t("common.time"), min_width=10, priority=3),
            Column(ctx.t("common.number"), min_width=8, priority=2),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=3),
            Column(ctx.t("common.verdict"), min_width=6, priority=2),
            Column(ctx.t("common.action"), min_width=6, priority=1),
        ]

    def title(self) -> str:
        return self.t("scan.history")

    def load(self) -> List[Sequence[Any]]:
        if self.number:
            result = self.backend.number_history(self.number, limit=200)
        else:
            result = self.backend.recent_events(limit=200)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        rows = []
        for row in result.data or []:
            rows.append(
                [
                    fmt.timestamp(row.get("timestamp"), short=True),
                    fmt.masked(row.get("number")),
                    fmt.integer(row.get("risk_score")),
                    fmt.status_word(row.get("verdict")),
                    fmt.status_word(row.get("action")),
                ]
            )
        return rows

    def intro(self, surface: Surface) -> List[str]:
        if self.number:
            return [surface.style(
                "{0}: {1}".format(self.t("common.number"), fmt.masked(self.number)),
                "label")]
        return []


class CompareScreen(Screen):
    """Side-by-side comparison of two scan results."""

    name = "scan_compare"

    def __init__(self, ctx: Any, first: str, second: str) -> None:
        Screen.__init__(self, ctx)
        self.first = first
        self.second = second
        self.left: Any = None
        self.right: Any = None
        self.errors: List[str] = []

    def title(self) -> str:
        return self.t("scan.compare")

    def refresh(self) -> None:
        self.errors = []
        for attribute, number in (("left", self.first), ("right", self.second)):
            result = self.backend.scan(number)
            if result.ok:
                setattr(self, attribute, result.data)
            else:
                setattr(self, attribute, None)
                self.errors.append("{0}: {1}".format(fmt.masked(number), result.error))

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("scan.compare.header"))]
        if self.left is None and self.right is None:
            lines.extend(surface.style(error, "err") for error in self.errors)
            return lines

        def cell(analysis: Any, attribute: str) -> str:
            if analysis is None:
                return fmt.PLACEHOLDER
            return fmt.text_or_placeholder(getattr(analysis, attribute, None))

        rows = [
            [t("scan.field.masked"),
             fmt.masked(getattr(self.left, "normalized_number", self.first)),
             fmt.masked(getattr(self.right, "normalized_number", self.second))],
            [t("scan.field.risk_score"), cell(self.left, "risk_score"),
             cell(self.right, "risk_score")],
            [t("common.confidence"), cell(self.left, "confidence"),
             cell(self.right, "confidence")],
            [t("scan.field.risk_level"), cell(self.left, "risk_level"),
             cell(self.right, "risk_level")],
            [t("common.verdict"), cell(self.left, "verdict"),
             cell(self.right, "verdict")],
            [t("scan.field.recommendation"), cell(self.left, "recommended_action"),
             cell(self.right, "recommended_action")],
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
        for error in self.errors:
            lines.append(surface.style(error, "err"))
        lines.append("")
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        return lines


class ScanCenterScreen(MenuScreen):
    """Scan Center menu."""

    name = "scan"
    title_key = "scan.title"

    def intro(self, surface: Surface) -> List[str]:
        return [
            surface.style(
                "{0}: {1}".format(self.t("scan.field.threshold"),
                                  _thresholds(self.ctx.cfg)),
                "muted",
            ),
            surface.style(
                "{0}: {1}".format(self.t("settings.scan_mode"),
                                  self.ctx.prefs.default_scan_mode),
                "muted",
            ),
        ]

    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        return [
            MenuItem("basic", t("scan.basic")),
            MenuItem("advanced", t("scan.advanced")),
            MenuItem("history", t("scan.history")),
            MenuItem("compare", t("scan.compare")),
        ]

    def activate(self, item: MenuItem) -> Optional[Action]:
        t = self.t
        if item.key == "history":
            return push(ScanHistoryScreen(self.ctx))

        if item.key == "compare":
            first = self.ctx.ask(t("scan.compare.first"))
            if not first:
                self.set_message(t("common.cancelled"), "info")
                return stay()
            second = self.ctx.ask(t("scan.compare.second"))
            if not second:
                self.set_message(t("common.cancelled"), "info")
                return stay()
            return push(CompareScreen(self.ctx, first, second))

        number = self.ctx.ask(t("prompt.number"))
        if not number:
            self.set_message(t("prompt.empty_input"), "warn")
            return stay()
        if item.key == "advanced":
            return push(AdvancedScanScreen(self.ctx, number))
        if self.ctx.prefs.default_scan_mode == "ADVANCED":
            return push(AdvancedScanScreen(self.ctx, number))
        return push(ScanResultScreen(self.ctx, number))


__all__ = [
    "AdvancedScanScreen",
    "CompareScreen",
    "ScanCenterScreen",
    "ScanHistoryScreen",
    "ScanResultScreen",
    "basic_sections",
]
