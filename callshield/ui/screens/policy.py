"""Policy Center.

Policy changes are persisted through the existing ``screening policy`` CLI
handler. The simulator calls :class:`callshield.policy.PolicyEngine` in a
read-only way: it never writes configuration, never touches the emergency file
and never influences the running daemon.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .. import formatters as fmt
from ..components import (
    card,
    kv,
    kv_block,
    notice,
    paragraph,
    section_title,
    Surface,
)
from .base import Action, MenuItem, MenuScreen, Screen, push, stay

POLICY_NAMES = ("RELAXED", "BALANCED", "STRICT")


def _int_or_none(raw: Any) -> Optional[int]:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value < 0 or value > 100:
        return None
    return value


class PolicyTestScreen(Screen):
    """Result of one simulated decision."""

    name = "policy_test"
    title_key = "policy.test"

    def __init__(self, ctx: Any, risk: int, confidence: int, mode: str,
                 policy_name: str) -> None:
        Screen.__init__(self, ctx)
        self.risk = risk
        self.confidence = confidence
        self.mode = mode
        self.policy_name = policy_name
        self.decision: Any = None

    def refresh(self) -> None:
        result = self.backend.policy_simulate(
            self.risk, self.confidence, mode=self.mode,
            policy_name=self.policy_name,
        )
        if result.ok:
            self.decision = result.data
        else:
            self.decision = None
            self.set_message(result.error, "err")

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("policy.test"))]
        lines.extend(
            kv_block(
                surface,
                [
                    (t("common.risk"), fmt.score(self.risk)),
                    (t("common.confidence"), fmt.percent(self.confidence)),
                    (t("common.mode"), self.mode),
                    (t("common.policy"), self.policy_name),
                ],
            )
        )
        lines.append("")
        decision = self.decision
        if decision is None:
            lines.extend(notice(surface, t("error.generic"), "err"))
            return lines
        rows = [
            (t("common.action"), getattr(decision, "action", None)),
            (t("blocks.recommended"), getattr(decision, "recommended_action", None)),
            (t("blocks.applied"), getattr(decision, "applied_action", None)),
            (t("common.mode"), getattr(decision, "mode", None)),
            (t("common.policy"), getattr(decision, "policy", None)),
            (t("common.reason"), getattr(decision, "reason", None)),
        ]
        lines.append(section_title(surface, t("common.result")))
        lines.extend(
            kv_block(
                surface,
                rows,
                status_keys=(t("common.action"), t("blocks.recommended"),
                             t("blocks.applied"), t("common.mode")),
            )
        )
        lines.append("")
        lines.extend(notice(surface, t("policy.simulation_note"), "info"))
        return lines

    def hints(self) -> List[str]:
        return [self.t("nav.back"), self.t("nav.quit")]


class PolicyScreen(MenuScreen):
    """Current thresholds, the simulator and the emergency control."""

    name = "policy"
    title_key = "policy.title"

    def __init__(self, ctx: Any) -> None:
        MenuScreen.__init__(self, ctx)
        self.snapshot: Dict[str, Any] = {}

    def refresh(self) -> None:
        self.snapshot = self.backend.policy_snapshot()

    @property
    def emergency(self) -> bool:
        return bool(self.snapshot.get("emergency_off"))

    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        current = str(self.snapshot.get("current") or "BALANCED")
        lines: List[str] = []
        lines.extend(
            kv_block(
                surface,
                [
                    (t("policy.current"), current),
                    (t("common.mode"), self.snapshot.get("mode")),
                    (t("screening.status"),
                     "ENABLED" if self.snapshot.get("enabled") else "DISABLED"),
                    (t("policy.emergency"),
                     "ENGAGED" if self.emergency else "CLEAR"),
                ],
                status_keys=(t("policy.current"), t("common.mode"),
                             t("screening.status"), t("policy.emergency")),
            )
        )

        policies = self.snapshot.get("policies") or {}
        card_width = max(20, min(surface.width, 64))
        inner_width = max(8, card_width - 4)
        for name in POLICY_NAMES:
            entry = policies.get(name) or {}
            lines.append("")
            title = name
            if name == current:
                title = "{0}  [{1}]".format(name, t("policy.current_marker"))
            card_lines = [
                kv(surface, t("policy.active_threshold"),
                   fmt.integer(entry.get("active_block")), width=inner_width,
                   label_width=16),
                kv(surface, t("common.confidence"),
                   fmt.integer(entry.get("confidence")), width=inner_width,
                   label_width=16),
            ]
            lines.extend(card(surface, card_lines, title=title,
                                   width=card_width))
        lines.append("")
        if self.emergency:
            lines.extend(notice(surface, t("policy.emergency_engaged"), "warn"))
        else:
            lines.extend(paragraph(surface, t("policy.emergency_clear"), role="muted"))
        return lines

    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        current = str(self.snapshot.get("current") or "BALANCED")
        items = [
            MenuItem("current", t("policy.current"), status=current),
            MenuItem("test", t("policy.test")),
            MenuItem("RELAXED", t("policy.relaxed"), enabled=current != "RELAXED"),
            MenuItem("BALANCED", t("policy.balanced"), enabled=current != "BALANCED"),
            MenuItem("STRICT", t("policy.strict"), enabled=current != "STRICT"),
        ]
        if self.emergency:
            items.append(MenuItem("emergency_reset", t("policy.emergency_reset"),
                                  status="ENGAGED"))
        else:
            items.append(MenuItem("emergency", t("policy.emergency_engage")))
        return items

    def activate(self, item: MenuItem) -> Optional[Action]:
        t = self.t
        key = item.key

        if key == "current":
            self.refresh()
            self.rebuild()
            self.set_message(t("common.done"), "ok")
            return stay()

        if key == "test":
            risk = _int_or_none(self.ctx.ask(t("policy.prompt_risk")))
            if risk is None:
                self.set_message(t("prompt.invalid_choice"), "warn")
                return stay()
            confidence = _int_or_none(self.ctx.ask(t("policy.prompt_confidence")))
            if confidence is None:
                self.set_message(t("prompt.invalid_choice"), "warn")
                return stay()
            return push(
                PolicyTestScreen(
                    self.ctx,
                    risk,
                    confidence,
                    str(self.snapshot.get("mode") or "DRY_RUN"),
                    str(self.snapshot.get("current") or "BALANCED"),
                )
            )

        if key in POLICY_NAMES:
            result = self.backend.set_screening_policy(key)
            ok = result.ok and (result.data or {}).get("exit_code") == 0
            self.set_message(
                t("policy.changed") if ok else t("error.generic"),
                "ok" if ok else "err",
            )
            self.refresh()
            self.rebuild()
            return stay()

        if key == "emergency":
            if not self.ctx.confirm(t("policy.confirm_emergency")):
                self.set_message(t("common.cancelled"), "info")
                return stay()
            result = self.backend.emergency_off()
            ok = result.ok and (result.data or {}).get("exit_code") == 0
            self.set_message(
                t("policy.emergency_engaged") if ok else t("error.generic"),
                "warn" if ok else "err",
            )
            self.refresh()
            self.rebuild()
            return stay()

        if key == "emergency_reset":
            if not self.ctx.confirm(t("policy.confirm_emergency_reset")):
                self.set_message(t("common.cancelled"), "info")
                return stay()
            result = self.backend.emergency_reset()
            ok = result.ok and (result.data or {}).get("exit_code") == 0
            self.set_message(
                t("policy.emergency_clear") if ok else t("error.generic"),
                "ok" if ok else "err",
            )
            self.refresh()
            self.rebuild()
            return stay()

        return None

    def outro(self, surface: Surface) -> List[str]:
        return paragraph(surface, self.t("policy.simulation_note"), role="muted")


__all__ = ["PolicyScreen", "PolicyTestScreen"]
