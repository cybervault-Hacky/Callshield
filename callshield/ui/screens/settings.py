"""Settings.

Everything on this screen is an *interface* preference stored in the UI state
file (``ui_state.json``). None of it reaches :mod:`callshield.config`, the
databases, the daemon, trust records, list entries or the screening/security
configuration — the reset action included, which rewrites that single JSON file
and nothing else.
"""

from __future__ import annotations

import os
from typing import Any, List, Optional, Sequence, Tuple

from .. import formatters as fmt
from ..components import Surface, kv_block, paragraph
from ..i18n import available_languages, language_label
from ..state.preferences import (
    APPEARANCE_CHOICES,
    REFRESH_CHOICES,
    SCAN_MODE_CHOICES,
    preferences_path,
)
from .base import (
    Action,
    MenuItem,
    MenuScreen,
    Screen,
    push,
    section_title,
    stay,
)


def _refresh_label(t: Any, seconds: Any) -> str:
    try:
        value = int(seconds)
    except (TypeError, ValueError):
        value = 2
    if value == 0:
        return t("settings.refresh.manual")
    return "{0}s".format(value)


def _appearance_label(t: Any, value: Any) -> str:
    key = str(value or "DARK").upper()
    return {
        "DARK": t("settings.appearance.dark"),
        "LIGHT": t("settings.appearance.light"),
        "SYSTEM": t("settings.appearance.system"),
    }.get(key, t("settings.appearance.dark"))


def _scan_mode_label(t: Any, value: Any) -> str:
    key = str(value or "BASIC").upper()
    if key == "ADVANCED":
        return t("settings.scan_mode.advanced")
    return t("settings.scan_mode.basic")


class ChoiceScreen(MenuScreen):
    """Generic single-choice list that writes one preference field."""

    name = "settings_choice"

    def __init__(
        self,
        ctx: Any,
        title: str,
        field: str,
        choices: Sequence[Tuple[Any, str]],
        note: str = "",
    ) -> None:
        self._title = str(title)
        self.field = field
        self.choices = list(choices)
        self.note = note
        MenuScreen.__init__(self, ctx)

    def title(self) -> str:
        return self._title

    def build_items(self) -> Sequence[MenuItem]:
        current = getattr(self.ctx.prefs, self.field, None)
        items = []
        for value, label in self.choices:
            selected = str(value) == str(current)
            items.append(
                MenuItem(
                    str(value),
                    label,
                    status="SELECTED" if selected else "",
                )
            )
        return items

    def intro(self, surface: Surface) -> List[str]:
        lines = [section_title(surface, self._title)]
        if self.note:
            lines.extend(paragraph(surface, self.note, role="muted"))
        return lines

    def activate(self, item: MenuItem) -> Optional[Action]:
        raw = item.key
        value: Any = raw
        if self.field == "refresh_seconds":
            try:
                value = int(raw)
            except ValueError:
                value = 2
        elif self.field in ("animation", "notifications"):
            value = raw == "True"
        saved = self.ctx.set_preference(self.field, value)
        self.set_message(
            self.t("settings.saved") if saved else self.t("settings.save_failed"),
            "ok" if saved else "err",
        )
        self.rebuild()
        return stay()


class LanguageScreen(ChoiceScreen):
    """Language picker. Technical command names are never translated."""

    name = "settings_language"

    def __init__(self, ctx: Any) -> None:
        ChoiceScreen.__init__(
            self,
            ctx,
            ctx.t("settings.language"),
            "language",
            [(code, label) for code, label in available_languages()],
        )

    def title(self) -> str:
        return self.t("settings.language")

    def activate(self, item: MenuItem) -> Optional[Action]:
        action = ChoiceScreen.activate(self, item)
        # The title and every label must follow the new language immediately.
        self._title = self.t("settings.language")
        self.rebuild()
        return action


class DataScreen(Screen):
    """Where CALLSHIELD keeps its files. Read-only."""

    name = "settings_data"
    title_key = "settings.data.title"

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        cfg = self.ctx.cfg
        rows = [
            (t("settings.data.database"), getattr(cfg, "database_path", "")),
            (t("settings.data.logs"), getattr(cfg, "log_file", "")),
            (t("settings.data.ui_state"), preferences_path(cfg)),
        ]
        try:
            from ... import config as config_module

            rows.insert(0, (t("settings.data.config"), str(config_module.CONFIG_PATH)))
        except Exception:  # pragma: no cover - defensive
            pass

        lines = [section_title(surface, t("settings.data.title"))]
        lines.extend(
            kv_block(
                surface,
                [(label, fmt.text_or_placeholder(value)) for label, value in rows],
            )
        )
        lines.append("")
        lines.extend(paragraph(surface, t("settings.data.note"), role="muted"))
        lines.extend(paragraph(surface, t("error.no_network"), role="muted"))
        return lines

    def hints(self) -> List[str]:
        return [self.t("nav.back"), self.t("nav.quit")]


class SettingsScreen(MenuScreen):
    """Interface preferences."""

    name = "settings"
    title_key = "settings.title"

    def intro(self, surface: Surface) -> List[str]:
        t = self.t
        prefs = self.ctx.prefs
        lines = [section_title(surface, t("settings.title"))]
        lines.extend(
            kv_block(
                surface,
                [
                    (t("settings.language"), language_label(prefs.language)),
                    (t("settings.appearance"), _appearance_label(t, prefs.appearance)),
                    (
                        t("settings.animation"),
                        t("settings.animation.on")
                        if prefs.animation
                        else t("settings.animation.off"),
                    ),
                    (t("settings.refresh"), _refresh_label(t, prefs.refresh_seconds)),
                    (
                        t("settings.scan_mode"),
                        _scan_mode_label(t, prefs.default_scan_mode),
                    ),
                    (
                        t("settings.notifications"),
                        t("settings.notifications.on")
                        if prefs.notifications
                        else t("settings.notifications.off"),
                    ),
                ],
            )
        )
        return lines

    def build_items(self) -> Sequence[MenuItem]:
        t = self.t
        prefs = self.ctx.prefs
        return [
            MenuItem("language", t("settings.language"),
                     status=language_label(prefs.language)),
            MenuItem("appearance", t("settings.appearance"),
                     status=_appearance_label(t, prefs.appearance)),
            MenuItem("animation", t("settings.animation"),
                     status=t("settings.animation.on") if prefs.animation
                     else t("settings.animation.off")),
            MenuItem("refresh", t("settings.refresh"),
                     status=_refresh_label(t, prefs.refresh_seconds)),
            MenuItem("scan_mode", t("settings.scan_mode"),
                     status=_scan_mode_label(t, prefs.default_scan_mode)),
            MenuItem("notifications", t("settings.notifications"),
                     status=t("common.enabled") if prefs.notifications
                     else t("common.disabled")),
            MenuItem("data", t("settings.data")),
            MenuItem("reset", t("settings.reset")),
        ]

    def outro(self, surface: Surface) -> List[str]:
        return paragraph(surface, self.t("settings.reset_scope"), role="muted")

    # ---------------------------------------------------------------- action
    def activate(self, item: MenuItem) -> Optional[Action]:
        t = self.t
        key = item.key

        if key == "language":
            return push(LanguageScreen(self.ctx))

        if key == "appearance":
            choices = [
                (value, _appearance_label(t, value)) for value in APPEARANCE_CHOICES
            ]
            return push(
                ChoiceScreen(self.ctx, t("settings.appearance"), "appearance", choices)
            )

        if key == "refresh":
            choices = [
                (value, _refresh_label(t, value)) for value in REFRESH_CHOICES
            ]
            return push(
                ChoiceScreen(self.ctx, t("settings.refresh"), "refresh_seconds",
                             choices)
            )

        if key == "scan_mode":
            choices = [
                (value, _scan_mode_label(t, value)) for value in SCAN_MODE_CHOICES
            ]
            return push(
                ChoiceScreen(self.ctx, t("settings.scan_mode"), "default_scan_mode",
                             choices)
            )

        if key in ("animation", "notifications"):
            field = key
            current = bool(getattr(self.ctx.prefs, field))
            saved = self.ctx.set_preference(field, not current)
            self.set_message(
                t("settings.saved") if saved else t("settings.save_failed"),
                "ok" if saved else "err",
            )
            self.rebuild()
            return stay()

        if key == "data":
            return push(DataScreen(self.ctx))

        if key == "reset":
            if not self.ctx.confirm(t("settings.reset_prompt")):
                self.set_message(t("common.cancelled"), "info")
                return stay()
            self.ctx.reset_preferences()
            self.set_message(t("settings.reset_done"), "ok")
            self.rebuild()
            return stay()

        return None


__all__ = [
    "ChoiceScreen",
    "DataScreen",
    "LanguageScreen",
    "SettingsScreen",
]
