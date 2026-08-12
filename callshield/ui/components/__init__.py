"""Reusable presentation components.

Every component is a pure function (or a small state holder) that turns data
into a list of terminal lines. No component reads the database, talks to the
daemon, opens a socket or runs a subprocess.
"""

from .base import Surface, blank
from .chrome import (
    breadcrumb,
    confirm_line,
    footer,
    header,
    notice,
    status_bar,
)
from .menu import Menu, MenuItem, render_menu
from .panel import (
    bullet_list,
    empty_state,
    kv,
    kv_block,
    panel,
    paragraph,
    rule,
    section_title,
)
from .progress import Spinner, progress_bar, score_meter, staged_lines
from .table import Column, fit_columns, table

__all__ = [
    "Column",
    "Menu",
    "MenuItem",
    "Spinner",
    "Surface",
    "blank",
    "breadcrumb",
    "bullet_list",
    "confirm_line",
    "empty_state",
    "fit_columns",
    "footer",
    "header",
    "kv",
    "kv_block",
    "notice",
    "panel",
    "paragraph",
    "progress_bar",
    "render_menu",
    "rule",
    "score_meter",
    "section_title",
    "staged_lines",
    "status_bar",
    "table",
]
