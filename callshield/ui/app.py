"""Application shell: context, render loop and input handling.

The shell owns the terminal. Screens only produce lines and return navigation
actions; everything that touches the terminal state (raw mode, clearing,
prompts, resize handling, Ctrl+C) lives here so it can be restored in exactly
one place.

Nothing in this module reads the database, talks to the daemon, opens a socket
or spawns a process: those go through ``callshield.ui.state.backend.Backend``,
which delegates to the existing CLI and service APIs.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, List, Optional, Sequence

from ..utils import EXIT_GENERAL, EXIT_OK
from . import formatters as fmt
from .components import Surface, breadcrumb, footer, header, notice
from .i18n import Translator
from .navigation import ScreenStack, keys as K
from .screens import base as screen_base
from .screens import make_screen as _make_screen
from .state import Backend, PreferencesStore, Result
from .theme import Capabilities, Glyphs, Theme, detect, detect_size, resolve_appearance

#: How long the loop waits for a key before re-rendering (seconds).
IDLE_POLL = 0.5
#: Lower bound for a live refresh so a busy screen cannot spin.
MIN_REFRESH = 1.0

CLEAR = "\x1b[H\x1b[2J\x1b[3J"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"


def _version() -> str:
    try:
        from .. import __version__

        return str(__version__)
    except Exception:  # pragma: no cover - defensive
        return "0.0.0"


class AppContext:
    """Everything a screen is allowed to reach."""

    def __init__(
        self,
        cfg: Any,
        *,
        caps: Optional[Capabilities] = None,
        backend: Optional[Backend] = None,
        store: Optional[PreferencesStore] = None,
        stdout: Any = None,
        stdin: Any = None,
        reader: Any = None,
    ) -> None:
        self.cfg = cfg
        self.stdout = stdout if stdout is not None else sys.stdout
        self.stdin = stdin if stdin is not None else sys.stdin
        self.caps = caps if caps is not None else detect(
            self.stdin, self.stdout,
            color_mode=str(getattr(cfg, "color_enabled", "AUTO") or "AUTO"),
        )
        self.backend = backend if backend is not None else Backend(cfg)
        self.store = store if store is not None else PreferencesStore(cfg)

        self.prefs = self.store.load()
        #: Non-fatal problem detected while loading preferences (shown once).
        self.startup_notice = ""
        if self.store.recovered:
            self.startup_notice = "error.corrupt_config"

        self.t = Translator(self.prefs.language)
        self.version = _version()
        self.surface = self._build_surface()
        self.reader = reader
        self.last_frame: List[str] = []

    # ------------------------------------------------------------- surface
    def _build_surface(self) -> Surface:
        appearance = resolve_appearance(self.prefs.appearance)
        theme = Theme(appearance, self.caps.color)
        return Surface(self.caps, theme, Glyphs(self.caps.unicode))

    def resize(self, caps: Capabilities) -> None:
        self.caps = caps
        self.surface = self._build_surface()

    # ------------------------------------------------------------ terminal
    def write(self, text: str) -> None:
        try:
            self.stdout.write(text)
            self.stdout.flush()
        except Exception:  # noqa: BLE001 - closed pipe, e.g. `callshield | head`
            pass

    def clear(self) -> None:
        if self.caps.interactive:
            self.write(CLEAR)

    def draw(self, lines: Sequence[str]) -> None:
        """Render a full frame."""

        self.last_frame = list(lines)
        payload = "\n".join(self.last_frame)
        if self.caps.interactive:
            self.write(CLEAR + payload + "\n")
        else:
            self.write(payload + "\n")

    # -------------------------------------------------------------- screens
    def make_screen(self, key: str) -> Optional[Any]:
        try:
            return _make_screen(key, self)
        except Exception:  # noqa: BLE001 - a broken screen must not kill the app
            return None

    # --------------------------------------------------------------- input
    def _suspend(self) -> None:
        """Leave raw mode so a normal line prompt behaves normally."""

        if self.reader is not None:
            try:
                self.reader.close()
            except Exception:  # noqa: BLE001
                pass
        if self.caps.interactive:
            self.write(SHOW_CURSOR)

    def _resume(self) -> None:
        if self.reader is not None:
            try:
                self.reader.open()
            except Exception:  # noqa: BLE001
                pass
        if self.caps.interactive:
            self.write(HIDE_CURSOR)

    def ask(self, prompt: str) -> Optional[str]:
        """Blocking line prompt. ``None`` means cancelled/interrupted."""

        if not self.caps.interactive:
            return None
        self._suspend()
        try:
            self.write("\n")
            answer = K.read_line(str(prompt), stream=self.stdin)
        except KeyboardInterrupt:
            answer = None
        finally:
            self._resume()
        if answer is None:
            return None
        return answer.strip()

    def confirm(self, question: str) -> bool:
        """Destructive-action prompt. Anything but an explicit yes is no."""

        answer = self.ask(question)
        if not answer:
            return False
        return answer.strip().lower() in ("y", "yes")

    def run_with_terminal(self, action: Callable[[], Any], notice: str = "") -> Any:
        """Hand the raw terminal to an existing CLI handler and its prompts."""

        self._suspend()
        self.clear()
        if notice:
            self.write(str(notice) + "\n\n")
        try:
            result = action()
        except KeyboardInterrupt:
            result = Result(error=self.t("app.interrupted"))
        except Exception as exc:  # noqa: BLE001
            result = Result(error=str(exc) or exc.__class__.__name__)
        try:
            self.write("\n")
            K.read_line(self.t("nav.press_enter") + " ", stream=self.stdin)
        except Exception:  # noqa: BLE001
            pass
        self._resume()
        return result

    # ---------------------------------------------------------- preferences
    def set_preference(self, field: str, value: Any) -> bool:
        """Write one interface preference. Never touches security config."""

        if not hasattr(self.prefs, field):
            return False
        previous = getattr(self.prefs, field)
        setattr(self.prefs, field, value)
        self.prefs = self.prefs.normalized()
        if getattr(self.prefs, field) != previous:
            self._apply_preferences()
        saved = self.store.save(self.prefs)
        return bool(saved)

    def reset_preferences(self) -> bool:
        """Restore default interface preferences (UI state file only)."""

        self.prefs = self.store.reset()
        self._apply_preferences()
        return self.store.last_error is None

    def _apply_preferences(self) -> None:
        self.t = Translator(self.prefs.language)
        self.surface = self._build_surface()

    @property
    def refresh_seconds(self) -> float:
        try:
            value = int(self.prefs.refresh_seconds)
        except (TypeError, ValueError):
            value = 2
        if value <= 0:
            return 0.0
        return max(MIN_REFRESH, float(value))


class Application:
    """Screen stack, render loop and global key handling."""

    def __init__(self, ctx: AppContext, reader: Any = None) -> None:
        self.ctx = ctx
        self.reader = reader if reader is not None else K.KeyReader(ctx.stdin)
        ctx.reader = self.reader
        self.stack = ScreenStack()
        self.running = False
        self.scroll = 0
        self.exit_code = EXIT_OK
        self._last_refresh = 0.0

    # ---------------------------------------------------------------- setup
    def start(self, root: Any = None) -> None:
        screen = root if root is not None else self.ctx.make_screen("dashboard")
        self.push(screen)

    def push(self, screen: Any) -> None:
        if screen is None:
            return
        self.stack.push(screen, self._safe(screen.title, ""))
        self.scroll = 0
        self._enter(screen)

    def _enter(self, screen: Any) -> None:
        try:
            screen.on_enter()
        except Exception as exc:  # noqa: BLE001
            self._fail(screen, exc)
        self._last_refresh = time.monotonic()

    def _fail(self, screen: Any, exc: BaseException) -> None:
        message = str(exc).strip() or exc.__class__.__name__
        try:
            screen.set_message(fmt.truncate(message, 200), "err")
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _safe(func: Callable[[], Any], default: Any) -> Any:
        try:
            return func()
        except Exception:  # noqa: BLE001
            return default

    @property
    def current(self) -> Optional[Any]:
        return self.stack.current

    # --------------------------------------------------------------- render
    def render(self) -> List[str]:
        """Compose the current frame. Never raises, never overflows the screen."""

        ctx = self.ctx
        surface = ctx.surface
        screen = self.current
        head = header(surface, ctx.t("app.title"), ctx.t("app.subtitle"), ctx.version)

        if screen is None:
            return head

        trail = self.stack.trail()
        if len(trail) > 1:
            head.append(breadcrumb(surface, trail))
        head.append("")

        if ctx.caps.cramped:
            from .theme import MIN_WIDTH

            head.extend(
                notice(surface, ctx.t("error.too_narrow", width=MIN_WIDTH), "warn")
            )
            head.append("")
            head.extend(footer(surface, [ctx.t("nav.quit")]))
            return head

        try:
            body = list(screen.body(surface))
        except Exception as exc:  # noqa: BLE001
            self._fail(screen, exc)
            body = notice(surface, ctx.t("error.generic"), "err")

        tail: List[str] = []
        message = getattr(screen, "message", "")
        level = getattr(screen, "level", "info")
        if message:
            tail.append("")
            tail.extend(notice(surface, message, level))
        # Back and Quit are always offered, but a screen may already list
        # them; de-duplicate so the footer never repeats itself.
        hints = list(self._safe(screen.hints, []) or [])
        hints.extend([ctx.t("nav.back"), ctx.t("nav.quit")])
        seen = set()
        unique = []
        for hint in hints:
            if hint and hint not in seen:
                seen.add(hint)
                unique.append(hint)
        tail.extend(footer(surface, unique))

        # Reserve one row for the scroll indicator so the frame always fits.
        room = ctx.caps.height - len(head) - len(tail) - 1
        body, indicator = self._clip(body, room, getattr(screen, "focus_line", None))

        lines = head + body
        if indicator:
            lines.append(indicator)
        lines.extend(tail)
        return lines

    def _clip(self, body: List[str], room: int, focus: Optional[int] = None):
        """Clip the body to ``room`` rows, honouring scroll offset and focus."""

        room = max(3, int(room))
        if len(body) <= room:
            self.scroll = 0
            return body, ""
        highest = len(body) - room
        if focus is not None and 0 <= focus < len(body):
            # Keep the focused line (the menu cursor) inside the window.
            if focus < self.scroll:
                self.scroll = focus
            elif focus >= self.scroll + room:
                self.scroll = focus - room + 1
        self.scroll = max(0, min(self.scroll, highest))
        window = body[self.scroll:self.scroll + room]
        indicator = self.ctx.surface.style(
            "{0} {1}-{2}/{3}".format(
                self.ctx.t("nav.page"),
                self.scroll + 1,
                self.scroll + len(window),
                len(body),
            ),
            "muted",
        )
        return window, indicator

    def draw(self) -> None:
        self.ctx.draw(self.render())

    # ---------------------------------------------------------------- input
    def _poll_resize(self) -> bool:
        columns, rows = detect_size(self.ctx.stdout)
        if columns == self.ctx.caps.width and rows == self.ctx.caps.height:
            return False
        self.ctx.resize(self.ctx.caps.replace(width=columns, height=rows))
        return True

    def timeout(self) -> Optional[float]:
        screen = self.current
        if screen is not None and getattr(screen, "live", False):
            interval = self.ctx.refresh_seconds
            if interval:
                return min(interval, IDLE_POLL)
        return IDLE_POLL

    def tick(self) -> bool:
        """Refresh a live screen when its interval has elapsed."""

        screen = self.current
        if screen is None or not getattr(screen, "live", False):
            return False
        interval = self.ctx.refresh_seconds
        if not interval:
            return False
        if time.monotonic() - self._last_refresh < interval:
            return False
        self.refresh_current()
        return True

    def refresh_current(self) -> None:
        screen = self.current
        if screen is None:
            return
        try:
            screen.refresh()
            if hasattr(screen, "rebuild"):
                screen.rebuild()
        except Exception as exc:  # noqa: BLE001
            self._fail(screen, exc)
        self._last_refresh = time.monotonic()

    def handle_key(self, key: str) -> bool:
        """Process one key. Returns False when the application should exit."""

        if not key:
            return True
        screen = self.current
        if screen is None:
            return False

        if key == K.INTERRUPT:
            self.exit_code = EXIT_OK
            return False

        action = None
        try:
            action = screen.handle(key)
        except KeyboardInterrupt:
            return False
        except Exception as exc:  # noqa: BLE001 - screens must never crash the app
            self._fail(screen, exc)
            return True

        if action is not None:
            return self._apply(action)

        # Unclaimed keys fall through to the global bindings.
        if K.is_quit(key):
            return False
        if key in (K.ESC, K.BACKSPACE):
            return self._back()
        if key in (K.UP, K.PAGE_UP):
            self.scroll = max(0, self.scroll - (1 if key == K.UP else 5))
            return True
        if key in (K.DOWN, K.PAGE_DOWN):
            self.scroll += 1 if key == K.DOWN else 5
            return True
        if key in ("r", "R"):
            self.refresh_current()
            return True
        if key in ("h", "H"):
            return self._apply(screen_base.home())
        return True

    def _apply(self, action: Any) -> bool:
        kind = getattr(action, "kind", screen_base.STAY)
        if kind == screen_base.QUIT:
            return False
        if kind == screen_base.POP:
            return self._back()
        if kind == screen_base.HOME:
            while len(self.stack) > 1:
                self.stack.pop()
            self.scroll = 0
            if self.current is not None:
                self.refresh_current()
            return True
        if kind == screen_base.PUSH:
            self.push(action.screen)
            return True
        return True

    def _back(self) -> bool:
        if len(self.stack) <= 1:
            # The root screen is the exit point; the user is never trapped.
            return False
        self.stack.pop()
        self.scroll = 0
        screen = self.current
        if screen is not None:
            self.refresh_current()
        return True

    # ----------------------------------------------------------------- loop
    def loop(self) -> int:
        self.running = True
        self.draw()
        while self.running:
            try:
                if self._poll_resize():
                    self.draw()
                key = self.reader.read_key(self.timeout())
                if not key:
                    if self.tick():
                        self.draw()
                    continue
                self.running = self.handle_key(key)
                if self.running:
                    self.draw()
            except KeyboardInterrupt:
                self.running = False
                self.exit_code = EXIT_OK
        return self.exit_code


# ------------------------------------------------------------------ non-tty
def non_interactive_lines(ctx: AppContext) -> List[str]:
    """Concise, non-interactive summary for pipes, scripts and CI."""

    t = ctx.t
    state, _pid = ctx.backend.daemon_state()
    events = ctx.backend.event_metrics()
    try:
        snapshot = ctx.backend.policy_snapshot()
    except Exception:  # noqa: BLE001
        snapshot = {}

    lines = [
        "CALLSHIELD {0}".format(ctx.version),
        t("app.subtitle"),
        "",
        "{0:<12}{1}".format(t("main.field.daemon"), fmt.status_word(state)),
        "{0:<12}{1}".format(t("main.field.database"),
                            "READY" if events.ok else "ERROR"),
        "{0:<12}{1}".format(t("main.field.policy"),
                            fmt.status_word(snapshot.get("current"))),
        "",
        t("main.no_android"),
        "Interactive interface requires a terminal. "
        "Use `callshield --help` for commands.",
    ]
    return lines


# --------------------------------------------------------------------- entry
def run(cfg: Any, argv: Optional[Sequence[str]] = None, *,
        stdin: Any = None, stdout: Any = None,
        ctx: Optional[AppContext] = None) -> int:
    """Launch the interface. Always restores the terminal before returning."""

    if ctx is None:
        ctx = AppContext(cfg, stdin=stdin, stdout=stdout)

    if not ctx.caps.interactive:
        ctx.draw(non_interactive_lines(ctx))
        return EXIT_OK

    from .screens.startup import run_startup

    reader = K.KeyReader(ctx.stdin)
    app = Application(ctx, reader=reader)
    exit_code = EXIT_OK
    try:
        ctx.write(HIDE_CURSOR)
        reader.open()
        report = run_startup(ctx, animate=bool(ctx.prefs.animation))
        root = ctx.make_screen("dashboard")
        if root is None:
            ctx.draw(non_interactive_lines(ctx))
            return EXIT_GENERAL
        app.start(root)
        if ctx.startup_notice:
            root.set_message(ctx.t(ctx.startup_notice), "warn")
        elif report.warnings:
            root.set_message(fmt.truncate(report.warnings[0], 160), "warn")
        exit_code = app.loop()
    except KeyboardInterrupt:
        exit_code = EXIT_OK
    finally:
        try:
            reader.close()
        finally:
            ctx.write(SHOW_CURSOR)
            ctx.clear()
            ctx.write(ctx.t("app.goodbye") + "\n")
    return exit_code


__all__ = [
    "AppContext",
    "Application",
    "IDLE_POLL",
    "MIN_REFRESH",
    "non_interactive_lines",
    "run",
]
