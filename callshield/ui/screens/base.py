"""Screen framework.

A screen is a small object that knows how to render itself into a list of
terminal lines and how to react to one key press. Screens never talk to the
database, the daemon, the filesystem or the network directly: everything is
requested through :class:`callshield.ui.state.backend.Backend`, which delegates
to the existing CLI/service APIs.

Screens return an :class:`Action` from ``handle`` so the application shell owns
all navigation. There is no hidden mode and no key that leads nowhere: ``Esc``
always pops, ``q`` always offers to quit.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence

from .. import formatters as fmt
from ..components import (
    Column,
    Menu,
    MenuItem,
    Surface,
    bullet_list,
    empty_state,
    kv,
    kv_block,
    notice,
    panel,
    paragraph,
    render_menu,
    rule,
    score_meter,
    section_title,
    status_bar,
    table,
)
from ..navigation import keys as K

# ---------------------------------------------------------------- actions
STAY = "STAY"
PUSH = "PUSH"
POP = "POP"
HOME = "HOME"
QUIT = "QUIT"


class Action:
    """What the shell should do after a key press."""

    __slots__ = ("kind", "screen")

    def __init__(self, kind: str = STAY, screen: Any = None) -> None:
        self.kind = kind
        self.screen = screen

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Action({0})".format(self.kind)


def stay() -> Action:
    return Action(STAY)


def push(screen: Any) -> Action:
    return Action(PUSH, screen)


def pop() -> Action:
    return Action(POP)


def home() -> Action:
    return Action(HOME)


def quit_app() -> Action:
    return Action(QUIT)


# ----------------------------------------------------------------- screen
class Screen:
    """Base screen: renders lines, consumes one key at a time."""

    name = "screen"
    title_key = ""
    #: Screens that display live data ask the shell to redraw on a timer.
    live = False

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.message = ""
        self.level = "info"
        self.scroll = 0
        #: Body line the shell should keep visible when clipping (or None).
        self.focus_line: Optional[int] = None

    # ------------------------------------------------------------- helpers
    @property
    def t(self):
        return self.ctx.t

    @property
    def backend(self):
        return self.ctx.backend

    def title(self) -> str:
        return self.t(self.title_key) if self.title_key else self.name

    def set_message(self, message: str, level: str = "info") -> None:
        self.message = str(message or "")
        self.level = level

    def clear_message(self) -> None:
        self.message = ""
        self.level = "info"

    def report(self, result: Any, success: str = "") -> bool:
        """Turn a :class:`Result` into a status line. True when it succeeded."""

        if getattr(result, "ok", False):
            if success:
                self.set_message(success, "ok")
            return True
        self.set_message(getattr(result, "error", "") or self.t("error.generic"), "err")
        return False

    # -------------------------------------------------------------- render
    def on_enter(self) -> None:
        """Called once when the screen becomes visible."""

    def refresh(self) -> None:
        """Re-read backend data. Called on entry and on manual refresh."""

    def body(self, surface: Surface) -> List[str]:
        return []

    def hints(self) -> List[str]:
        return [
            self.t("nav.hint"),
        ]

    # --------------------------------------------------------------- input
    def handle(self, key: str) -> Optional[Action]:
        return None


class MenuScreen(Screen):
    """A screen whose primary content is a selectable menu."""

    numbered = False
    #: Heading printed above the menu.
    menu_title_key = "nav.menu"

    def __init__(self, ctx: Any) -> None:
        Screen.__init__(self, ctx)
        self.menu = Menu([])

    # ------------------------------------------------------------ contents
    def build_items(self) -> Sequence[MenuItem]:
        return []

    def intro(self, surface: Surface) -> List[str]:
        return []

    def outro(self, surface: Surface) -> List[str]:
        return []

    def rebuild(self) -> None:
        items = list(self.build_items())
        if self.menu.items:
            self.menu.replace(items)
        else:
            self.menu = Menu(items)

    def on_enter(self) -> None:
        self.refresh()
        self.rebuild()

    def body(self, surface: Surface) -> List[str]:
        lines: List[str] = []
        lines.extend(self.intro(surface))
        if lines:
            lines.append("")
        lines.append(section_title(surface, self.t(self.menu_title_key)))
        # Tell the shell which line to keep on screen when the body is clipped,
        # so the highlighted entry is never scrolled out of view.
        self.focus_line = len(lines) + self.menu.index
        lines.extend(render_menu(surface, self.menu, numbered=self.numbered))
        tail = self.outro(surface)
        if tail:
            lines.append("")
            lines.extend(tail)
        return lines

    def hints(self) -> List[str]:
        return [self.t("nav.hint"), self.t("nav.number_hint")]

    # -------------------------------------------------------------- action
    def activate(self, item: MenuItem) -> Optional[Action]:
        return None

    def handle(self, key: str) -> Optional[Action]:
        if key in (K.UP, "k", "K"):
            self.menu.move(-1)
            return stay()
        if key in (K.DOWN, "j", "J"):
            self.menu.move(1)
            return stay()
        if key == K.HOME:
            self.menu.first()
            return stay()
        if key == K.END:
            self.menu.last()
            return stay()
        if key == K.ENTER:
            item = self.menu.selected
            if item is None:
                return stay()
            self.clear_message()
            return self.activate(item)
        if K.is_digit(key):
            item = self.menu.select_number(int(key))
            if item is None:
                self.set_message(self.t("prompt.invalid_choice"), "warn")
                return stay()
            self.clear_message()
            return self.activate(item)
        return None


class ListScreen(Screen):
    """A paged, read-only table of records."""

    columns: Sequence[Column] = ()
    empty_key = "common.empty"
    page_size = 10

    def __init__(self, ctx: Any) -> None:
        Screen.__init__(self, ctx)
        from ..navigation import Pager

        self.rows: List[Sequence[Any]] = []
        self.pager = Pager(self.page_size, 0)

    def load(self) -> List[Sequence[Any]]:
        return []

    def refresh(self) -> None:
        self.rows = list(self.load())
        self.pager.set_total(len(self.rows))

    def on_enter(self) -> None:
        self.refresh()

    def intro(self, surface: Surface) -> List[str]:
        return []

    def body(self, surface: Surface) -> List[str]:
        lines = list(self.intro(surface))
        if lines:
            lines.append("")
        page = self.pager.slice(self.rows)
        lines.extend(
            table(
                surface,
                self.columns,
                page,
                empty_message=self.t(self.empty_key),
            )
        )
        if self.rows:
            lines.append("")
            lines.append(
                surface.style(
                    "{0}   {1}".format(
                        self.t(
                            "history.page",
                            page=self.pager.page,
                            pages=self.pager.pages,
                        ),
                        self.t(
                            "history.showing",
                            shown=len(page),
                            total=len(self.rows),
                        ),
                    ),
                    "muted",
                )
            )
        return lines

    def hints(self) -> List[str]:
        return [self.t("history.hint")]

    def handle(self, key: str) -> Optional[Action]:
        if key in (K.PAGE_DOWN, "n", "N", K.RIGHT):
            self.pager.next_page()
            return stay()
        if key in (K.PAGE_UP, "p", "P", K.LEFT):
            self.pager.previous_page()
            return stay()
        if key == K.HOME:
            self.pager.first_page()
            return stay()
        if key == K.END:
            self.pager.last_page()
            return stay()
        return None


class DetailScreen(Screen):
    """A static, scrollable detail view built from pre-rendered sections."""

    def __init__(self, ctx: Any, title: str, sections: Any = None) -> None:
        Screen.__init__(self, ctx)
        self._title = str(title)
        self._sections = sections or []

    def title(self) -> str:
        return self._title

    def body(self, surface: Surface) -> List[str]:
        lines: List[str] = []
        for section in self._sections:
            if callable(section):
                produced = section(surface)
            else:
                produced = section
            if isinstance(produced, str):
                lines.append(produced)
            else:
                lines.extend(produced)
        return lines

    def hints(self) -> List[str]:
        return [self.t("nav.back"), self.t("nav.quit")]


__all__ = [
    "Action",
    "Column",
    "DetailScreen",
    "HOME",
    "ListScreen",
    "Menu",
    "MenuItem",
    "MenuScreen",
    "POP",
    "PUSH",
    "QUIT",
    "STAY",
    "Screen",
    "Surface",
    "bullet_list",
    "empty_state",
    "fmt",
    "home",
    "kv",
    "kv_block",
    "notice",
    "panel",
    "paragraph",
    "pop",
    "push",
    "quit_app",
    "render_menu",
    "rule",
    "score_meter",
    "section_title",
    "stay",
    "status_bar",
    "table",
]
