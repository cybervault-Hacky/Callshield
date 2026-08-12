"""About screen.

Fixed, factual product information. Nothing here is fetched: the strings are
constants, the version comes from the installed package, and the platform line
describes the environments CALLSHIELD actually supports. CALLSHIELD is a
Termux/Linux command line tool, not an Android application — the Android
Bridge is shown as NOT VERIFIED and nothing implies otherwise.
"""

from __future__ import annotations

from typing import Any, List, Optional

from ..components import Surface, kv_block, paragraph, section_title
from .base import Action, Screen

PRODUCT = "CALLSHIELD"
AUTHOR = "Sarthak Bharambe"
YOUTUBE = "CyberVault"
INSTAGRAM = "@cyber_vault123"
PLATFORM = "Termux / Linux"
LICENSE = "MIT"


class AboutScreen(Screen):
    """Product, author and architecture information."""

    name = "about"
    title_key = "about.title"

    def body(self, surface: Surface) -> List[str]:
        t = self.t
        lines = [section_title(surface, PRODUCT)]
        lines.append(surface.style(t("about.tagline"), "muted"))
        lines.append("")
        lines.extend(
            kv_block(
                surface,
                [
                    (t("about.version"), self.ctx.version),
                    (t("about.developer"), AUTHOR),
                    (t("about.youtube"), YOUTUBE),
                    (t("about.instagram"), INSTAGRAM),
                    (t("about.platform"), PLATFORM),
                    (t("about.license"), LICENSE),
                ],
            )
        )
        lines.append("")
        lines.append(section_title(surface, t("about.architecture")))
        lines.extend(paragraph(surface, t("about.architecture_text")))
        lines.append("")
        lines.append(section_title(surface, t("about.android_bridge")))
        lines.extend(
            kv_block(
                surface,
                [(t("screening.android"), "NOT VERIFIED")],
                status_keys=(t("screening.android"),),
            )
        )
        lines.extend(paragraph(surface, t("screening.not_verified"), role="muted"))
        lines.append("")
        lines.extend(paragraph(surface, t("error.no_network"), role="muted"))
        return lines

    def handle(self, key: str) -> Optional[Action]:
        return None

    def hints(self) -> List[str]:
        return [self.t("nav.back"), self.t("nav.quit")]


__all__ = ["AboutScreen", "AUTHOR", "INSTAGRAM", "LICENSE", "PLATFORM", "PRODUCT",
           "YOUTUBE"]
