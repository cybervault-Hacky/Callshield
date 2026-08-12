"""Block Center.

Two things live here:

* the local blacklist / whitelist, edited through the existing ``block``,
  ``unblock``, ``allow`` and ``unallow`` CLI handlers;
* the screening decision log, which records what the policy engine
  recommended, what was applied and whether a rejection was actually
  confirmed by the device.

The interface never rejects a call and never edits a decision record.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from .. import formatters as fmt
from ..components import Column, kv_block, paragraph, Surface, table
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


class ListEntriesScreen(ListScreen):
    """Masked view of one stored list."""

    name = "block_list"
    empty_key = "common.empty"

    def __init__(self, ctx: Any, list_type: str) -> None:
        self.columns = (
            Column(ctx.t("common.number"), min_width=10, priority=3),
            Column(ctx.t("common.risk"), min_width=6, priority=1),
            Column(ctx.t("common.score"), align="right", min_width=3, priority=1),
            Column(ctx.t("common.reason"), min_width=8, priority=2),
            Column(ctx.t("common.time"), min_width=10, priority=2),
        )
        ListScreen.__init__(self, ctx)
        self.list_type = list_type

    def title(self) -> str:
        return self.t("blocks.blacklist") if self.list_type == "blacklist" \
            else self.t("blocks.whitelist")

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.list_numbers(self.list_type, limit=500)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        rows = []
        for entry in result.data or []:
            rows.append(
                [
                    fmt.masked(entry.get("number")),
                    fmt.status_word(entry.get("reputation")),
                    fmt.integer(entry.get("risk_score")),
                    fmt.text_or_placeholder(entry.get("reason")),
                    fmt.timestamp(entry.get("updated_at"), short=True),
                ]
            )
        return rows

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.title()),
            surface.style(self.t("common.masked_note"), "muted"),
        ]


class BlockDetailScreen(Screen):
    """One screening decision, exactly as the policy engine recorded it."""

    name = "block_detail"
    title_key = "blocks.inspect"

    FIELDS: Sequence[str] = (
        "timestamp",
        "number_masked",
        "risk",
        "confidence",
        "policy_name",
        "threshold",
        "confidence_threshold",
        "recommended_action",
        "applied_action",
        "reason",
        "policy_reason",
        "emergency_off",
        "mode",
        "actually_rejected",
        "rejection_confirmed_at",
        "source",
    )

    def __init__(self, ctx: Any, decision_id: Any) -> None:
        Screen.__init__(self, ctx)
        self.decision_id = decision_id
        self.record: Optional[Dict[str, Any]] = None

    def refresh(self) -> None:
        result = self.backend.inspect_block(self.decision_id)
        self.record = result.data if result.ok else None
        if not result.ok:
            self.set_message(result.error, "err")

    def on_enter(self) -> None:
        self.refresh()

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        if not self.record:
            return list(empty_state(surface, t("blocks.none")))
        rows = []
        for field in self.FIELDS:
            if field in self.record:
                value = self.record[field]
                if field in ("emergency_off", "actually_rejected"):
                    value = fmt.yes_no(value)
                elif field == "timestamp":
                    value = fmt.timestamp(value)
                rows.append((field, value))
        lines = [section_title(surface, t("blocks.inspect"))]
        lines.extend(
            kv_block(
                surface,
                rows,
                status_keys=("recommended_action", "applied_action", "mode"),
            )
        )
        lines.append("")
        lines.extend(paragraph(surface, t("screening.not_verified"), role="muted"))
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        return lines

    def hints(self) -> List[str]:
        return [self.t("nav.back"), self.t("nav.quit")]


class RecentBlocksScreen(ListScreen):
    """Applied block decisions with the recommended/applied/rejected split."""

    name = "blocks_recent"
    title_key = "blocks.recent"
    empty_key = "blocks.none"

    def __init__(self, ctx: Any) -> None:
        self.columns = (
            Column("ID", align="right", min_width=2, priority=2),
            Column(ctx.t("common.time"), min_width=10, priority=3),
            Column(ctx.t("common.number"), min_width=10, priority=3),
            Column(ctx.t("blocks.recommended"), min_width=6, priority=2),
            Column(ctx.t("blocks.applied"), min_width=6, priority=1),
            Column(ctx.t("blocks.rejected"), min_width=3, priority=1),
        )
        ListScreen.__init__(self, ctx)

    def load(self) -> List[Sequence[Any]]:
        result = self.backend.recent_blocks(limit=200)
        if not result.ok:
            self.set_message(result.error, "err")
            return []
        rows = []
        for row in result.data or []:
            rows.append(
                [
                    fmt.integer(row.get("id")),
                    fmt.timestamp(row.get("timestamp"), short=True),
                    fmt.text_or_placeholder(row.get("number_masked")),
                    fmt.status_word(row.get("recommended_action")),
                    fmt.status_word(row.get("applied_action")),
                    fmt.yes_no(row.get("actually_rejected")),
                ]
            )
        return rows

    def intro(self, surface: Surface) -> List[str]:
        return [
            section_title(surface, self.t("blocks.recent")),
            surface.style(self.t("screening.not_verified"), "muted"),
        ]

    def handle(self, key: str) -> Optional[Action]:
        if key in ("i", "I"):
            raw = self.ctx.ask(self.t("blocks.prompt_id"))
            try:
                decision_id = int(str(raw).strip())
            except (TypeError, ValueError):
                self.set_message(self.t("prompt.invalid_choice"), "warn")
                return stay()
            return push(BlockDetailScreen(self.ctx, decision_id))
        return ListScreen.handle(self, key)

    def hints(self) -> List[str]:
        return [self.t("history.hint"), self.t("blocks.inspect") + " (i)"]


class BlockScreen(MenuScreen):
    """Block Center menu."""

    name = "blocks"
    title_key = "blocks.title"

    def __init__(self, ctx: Any) -> None:
        MenuScreen.__init__(self, ctx)
        self.blacklist = 0
        self.whitelist = 0
        self.decisions = 0

    def refresh(self) -> None:
        black = self.backend.list_numbers("blacklist", limit=500)
        white = self.backend.list_numbers("whitelist", limit=500)
        blocks = self.backend.recent_blocks(limit=200)
        self.blacklist = len(black.data or []) if black.ok else 0
        self.whitelist = len(white.data or []) if white.ok else 0
        self.decisions = len(blocks.data or []) if blocks.ok else 0

    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, t("blocks.title"))]
        lines.extend(
            kv_block(
                surface,
                [
                    (t("blocks.blacklist"), fmt.integer(self.blacklist)),
                    (t("blocks.whitelist"), fmt.integer(self.whitelist)),
                    (t("blocks.recent"), fmt.integer(self.decisions)),
                ],
            )
        )
        lines.extend(paragraph(surface, t("common.masked_note"), role="muted"))
        return lines

    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        return [
            MenuItem("blacklist", t("blocks.blacklist"),
                     status=fmt.integer(self.blacklist)),
            MenuItem("whitelist", t("blocks.whitelist"),
                     status=fmt.integer(self.whitelist)),
            MenuItem("add_block", t("blocks.add_block")),
            MenuItem("add_allow", t("blocks.add_allow")),
            MenuItem("remove_block", t("blocks.remove_block"),
                     enabled=self.blacklist > 0),
            MenuItem("remove_allow", t("blocks.remove_allow"),
                     enabled=self.whitelist > 0),
            MenuItem("recent", t("blocks.recent"),
                     status=fmt.integer(self.decisions)),
            MenuItem("inspect", t("blocks.inspect"), enabled=self.decisions > 0),
        ]

    def activate(self, item: MenuItem) -> Optional[Action]:
        t = self.t
        key = item.key

        if key == "blacklist":
            return push(ListEntriesScreen(self.ctx, "blacklist"))
        if key == "whitelist":
            return push(ListEntriesScreen(self.ctx, "whitelist"))
        if key == "recent":
            return push(RecentBlocksScreen(self.ctx))

        if key == "inspect":
            raw = self.ctx.ask(t("blocks.prompt_id"))
            try:
                decision_id = int(str(raw).strip())
            except (TypeError, ValueError):
                self.set_message(t("prompt.invalid_choice"), "warn")
                return stay()
            return push(BlockDetailScreen(self.ctx, decision_id))

        actions = {
            "add_block": ("block", "blocks.confirm_block"),
            "add_allow": ("allow", "blocks.confirm_allow"),
            "remove_block": ("unblock", "blocks.confirm_remove"),
            "remove_allow": ("unallow", "blocks.confirm_remove"),
        }
        if key not in actions:
            return None
        action, question = actions[key]

        number = self.ctx.ask(t("prompt.number"))
        if not number:
            self.set_message(t("prompt.empty_input"), "warn")
            return stay()
        check = self.backend.normalize(number)
        if not check.ok:
            self.set_message(t("prompt.invalid_number"), "warn")
            return stay()
        normalized = (check.data or {}).get("normalized") or number
        if not self.ctx.confirm(t(question)):
            self.set_message(t("common.cancelled"), "info")
            return stay()
        reason = ""
        if action in ("block", "allow"):
            reason = self.ctx.ask(t("reports.prompt_reason")) or ""
        result = self.backend.list_action(action, normalized, reason)
        ok = result.ok and (result.data or {}).get("exit_code") == 0
        self.set_message(
            t("common.done") if ok else t("error.generic"),
            "ok" if ok else "err",
        )
        self.refresh()
        self.rebuild()
        return stay()


__all__ = [
    "BlockDetailScreen",
    "BlockScreen",
    "ListEntriesScreen",
    "RecentBlocksScreen",
]
