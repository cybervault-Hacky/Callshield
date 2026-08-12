"""About screen.

Fixed, factual product information. Nothing here is fetched: the strings are
constants, the version comes from the installed package, and the platform line
describes the environments CALLSHIELD actually supports. CALLSHIELD is a
Termux/Linux command line tool, not an Android application.
"""

from __future__ import annotations

from typing import Any, List, Optional

from ..components import Surface, kv_block, paragraph
from .base import Action, Screen, section_title

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
        lines.extend(
            kv_block(
                surface,
                [
                    (t("about.version"), self.ctx.version),
                    (t("about.author"), AUTHOR),
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
        lines.extend(paragraph(surface, t("error.no_network"), role="muted"))
        lines.extend(paragraph(surface, t("main.no_android"), role="muted"))
        return lines

    def handle(self, key: str) -> Optional[Action]:
        return None

    def hints(self) -> List[str]:
        return [self.t("nav.back"), self.t("nav.quit")]


__all__ = ["AboutScreen", "AUTHOR", "INSTAGRAM", "LICENSE", "PLATFORM", "PRODUCT",
           "YOUTUBE"]
