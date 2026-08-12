"""Professional redesign tests for the Phase 8.5 TUI.

These tests lock in the *presentation* redesign: the structured dashboard, the
quiet section headers, the minimal menu highlight (no full-line inverse
video), the status-badge vocabulary, the startup ``[OK]`` sequence, responsive
rendering at every tested width, masking, terminal restoration and the
presentation-only architecture. They intentionally do not re-test the backend:
every value still comes from the existing engines through the Backend.
"""

import os
import types
import unittest
from unittest import mock

from callshield.ui import app as app_mod
from callshield.ui import formatters as fmt
from callshield.ui.navigation import keys as K
from callshield.ui.screens import REGISTRY
from callshield.ui.screens import startup as startup_mod
from callshield.ui.theme import Theme
from tests._common import IsolatedEnv, run_cli
from tests._ui import (
    ScriptedContext,
    caps,
    emoji_characters,
    make_app,
    plain,
    render,
)


class RedesignCase(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()


# ------------------------------------------------------------ dashboard
class TestDashboardRedesign(RedesignCase):
    def test_sections_render_in_reading_order(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70))
        text = render(app)
        order = []
        for key in ("main.section.system", "main.section.threat",
                    "main.section.intelligence", "main.section.actions"):
            order.append(text.index(ctx.t(key)))
        self.assertEqual(order, sorted(order))

    def test_system_section_lists_daemon_engine_database_ipc_policy(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70))
        text = render(app)
        for key in ("main.field.daemon", "main.field.engine",
                    "main.field.database", "main.field.ipc",
                    "main.field.policy"):
            self.assertIn(ctx.t(key), text)

    def test_status_words_are_visible_not_just_coloured(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70))
        text = render(app)
        self.assertTrue(any(word in text for word in
                            ("READY", "OFFLINE", "STOPPED", "DISABLED")))

    def test_dashboard_footer_strips_daemon_policy_screening(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70))
        text = render(app)
        self.assertIn(ctx.t("main.field.daemon"), text)
        self.assertIn(ctx.t("main.field.screening"), text)

    def test_dashboard_is_not_a_wall_of_plain_text(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70,
                                                color=True))
        # Section titles must be styled headings (title role), not body text.
        raw = "\n".join(app.render())
        self.assertIn(Theme("DARK", True).code("title"), raw)


# ------------------------------------------------------------- selection
class TestSelectionHighlight(RedesignCase):
    def test_selection_uses_cursor_not_inverse_video(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70,
                                                color=True))
        app.handle_key(K.DOWN)
        raw = "\n".join(app.render())
        self.assertNotIn("\x1b[7m", raw, "full-line inverse video banned")

    def test_cursor_precedes_the_selected_label(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70))
        app.handle_key(K.DOWN)
        selected = app.current.menu.selected
        lines = plain(app.render()).split("\n")
        cursor_lines = [line for line in lines
                        if app.ctx.surface.glyph("cursor") in line]
        self.assertTrue(cursor_lines)
        self.assertIn(selected.label, cursor_lines[0])

    def test_non_selected_items_have_no_cursor(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70))
        lines = plain(app.render()).split("\n")
        marker = app.ctx.surface.glyph("cursor")
        selected = app.current.menu.selected
        for line in lines:
            if marker in line:
                self.assertIn(selected.label, line)


# ---------------------------------------------------------- status badges
class TestStatusBadges(RedesignCase):
    def test_status_words_survive_verbatim(self):
        theme = Theme("DARK", color=True)
        for word in ("RUNNING", "READY", "ONLINE", "DISABLED", "ACTIVE",
                     "DRY RUN", "NOT VERIFIED", "WARNING", "ERROR"):
            styled = theme.status(word)
            self.assertIn(word, styled)
            self.assertNotIn("_", styled.replace("_", ""))

    def test_placeholder_is_never_mangled_into_underscores(self):
        theme = Theme("DARK", color=True)
        self.assertIn("--", theme.status("--"))
        self.assertNotIn("__", theme.status("--"))
        self.assertEqual(fmt.status_word("--"), "--")

    def test_badge_colours_are_muted_not_neon(self):
        # The semantic palette must stay within the 256-colour range and must
        # never use the high-intensity background inversions.
        theme = Theme("DARK", color=True)
        for role in ("ok", "warn", "err", "info", "selected", "accent"):
            code = theme.code(role)
            self.assertTrue(code.startswith("\x1b["), role)
            self.assertNotIn("7m", code, role)


# ----------------------------------------------------------- responsive
class TestResponsiveWidths(RedesignCase):
    def test_no_screen_overflows_at_any_tested_width(self):
        for width in (20, 40, 60, 80, 120, 200):
            ctx, app = make_app(self.cfg, caps=caps(width=width, height=30))
            for key in REGISTRY:
                screen = ctx.make_screen(key)
                screen.on_enter()
                app.stack.push(screen, screen.title())
                for line in plain(app.render()).split("\n"):
                    self.assertLessEqual(len(line), width,
                                         (key, width, line))
                app.stack.pop()

    def test_very_narrow_terminal_asks_for_more_room(self):
        ctx, app = make_app(self.cfg, caps=caps(width=20, height=10))
        text = render(app)
        self.assertIn("WARNING", text)
        self.assertIn(ctx.t("nav.quit"), text)
        self.assertIn("small", text.lower())

    def test_wide_terminal_keeps_columns_readable(self):
        ctx, app = make_app(self.cfg, caps=caps(width=200, height=50))
        for line in plain(app.render()).split("\n"):
            self.assertLessEqual(len(line), 200)


# -------------------------------------------------------------- masking
class TestMasking(RedesignCase):
    def test_scan_result_card_masks_the_number(self):
        number = "+919876500999"
        run_cli(self.cfg, "scan", number)
        ctx, app = make_app(self.cfg, screen_key="scan",
                            answers=[number], caps=caps(width=100, height=70))
        app.handle_key("1")
        text = render(app)
        self.assertNotIn(number, text)
        self.assertIn("*", text)

    def test_monitor_stream_masks_numbers(self):
        number = "+919876500555"
        run_cli(self.cfg, "scan", number)
        ctx, app = make_app(self.cfg, screen_key="monitor",
                            caps=caps(width=100, height=60))
        text = render(app)
        self.assertNotIn(number, text)
        self.assertIn("*", text)


# ------------------------------------------------------------- settings
class TestSettingsGroups(RedesignCase):
    def test_settings_are_grouped_under_general_scan_data(self):
        ctx, app = make_app(self.cfg, screen_key="settings",
                            caps=caps(width=100, height=60))
        text = render(app)
        for key in ("settings.group.general", "settings.group.scan",
                    "settings.group.data"):
            self.assertIn(ctx.t(key), text)
        self.assertLess(text.index(ctx.t("settings.group.general")),
                        text.index(ctx.t("settings.group.scan")))
        self.assertLess(text.index(ctx.t("settings.group.scan")),
                        text.index(ctx.t("settings.group.data")))

    def test_each_setting_shows_its_current_value(self):
        ctx, app = make_app(self.cfg, screen_key="settings",
                            caps=caps(width=100, height=60))
        text = render(app)
        self.assertIn("English", text)
        self.assertIn("Dark", text)


# --------------------------------------------------------------- startup
class TestStartupRedesign(RedesignCase):
    def test_completed_stages_carry_ok_markers(self):
        ctx = ScriptedContext(self.cfg, caps=caps(width=100, height=40))
        text = plain(startup_mod.render_frame(ctx.surface, ctx.t, 9, None,
                                              "0.8.0"))
        self.assertEqual(text.count("[OK]"), len(startup_mod.STAGE_KEYS))

    def test_partial_stages_show_ok_only_for_completed(self):
        ctx = ScriptedContext(self.cfg, caps=caps(width=100, height=40))
        text = plain(startup_mod.render_frame(ctx.surface, ctx.t, 2, None,
                                              "0.8.0"))
        self.assertEqual(text.count("[OK]"), 2)
        for key in startup_mod.STAGE_KEYS[:2]:
            self.assertIn(ctx.t(key), text)

    def test_startup_frames_have_no_emoji_and_no_spinner_bars(self):
        ctx = ScriptedContext(self.cfg, caps=caps(width=100, height=40))
        text = plain(startup_mod.render_frame(ctx.surface, ctx.t, 9, None,
                                              "0.8.0"))
        self.assertEqual(emoji_characters(text), [])
        for char in ("|", "/", "-", "\\"):
            # Only the ASCII fallback glyphs may appear; the stage list itself
            # must not render a rotating bar.
            self.assertNotIn(" {0} ".format(char), text)

    def test_startup_can_be_cancelled_with_q(self):
        read_fd, write_fd = os.pipe()
        os.write(write_fd, b"q")
        try:
            class FakeStream:
                def fileno(self):
                    return read_fd

            ctx = types.SimpleNamespace(
                caps=types.SimpleNamespace(interactive=True),
                stdin=FakeStream(),
            )
            self.assertTrue(startup_mod._should_cancel(ctx))
            # A stream without pending input is never cancelled.
            empty = types.SimpleNamespace(
                caps=types.SimpleNamespace(interactive=True),
                stdin=FakeStream(),
            )
            self.assertFalse(startup_mod._should_cancel(empty))
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_startup_skip_in_non_interactive_mode(self):
        ctx = ScriptedContext(self.cfg, caps=caps(interactive=False))
        report = startup_mod.run_startup(ctx, animate=False)
        self.assertTrue(report.database_ok)
        self.assertEqual(ctx.written, "")


# ------------------------------------------------------- terminal safety
class TestTerminalSafety(RedesignCase):
    def test_run_restores_cursor_and_writes_goodbye(self):
        ctx = ScriptedContext(self.cfg,
                              caps=caps(width=80, height=40, interactive=True))
        with mock.patch.object(app_mod.Application, "loop", return_value=0):
            code = app_mod.run(self.cfg, ctx=ctx)
        self.assertEqual(code, 0)
        self.assertIn("\x1b[?25h", ctx.written, "cursor restored")
        self.assertIn(ctx.t("app.goodbye"), ctx.written)

    def test_esc_at_root_exits_and_q_quits_from_any_depth(self):
        ctx, app = make_app(self.cfg)
        self.assertFalse(app.handle_key(K.ESC))
        app.handle_key("2")
        self.assertFalse(app.handle_key("q"))

    def test_ctrl_c_exits_cleanly(self):
        ctx, app = make_app(self.cfg)
        self.assertFalse(app.handle_key(K.INTERRUPT))
        self.assertEqual(app.exit_code, 0)


# ------------------------------------------------- architecture boundary
class TestPresentationOnly(RedesignCase):
    def test_screens_never_import_engines_directly(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "callshield/ui"
        forbidden_modules = (
            "detector", "reputation", "policy", "adaptive", "events",
            "database", "daemon", "normalizer", "scoring", "rules",
        )
        violations = []
        for path in sorted((root / "screens").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"),
                             filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if any("." + name in module or module == name
                           for name in forbidden_modules):
                        violations.append((path.name, node.lineno, module))
        self.assertEqual(violations, [])

    def test_all_screens_render_without_emoji(self):
        ctx, _app = make_app(self.cfg)
        for key in REGISTRY:
            screen = ctx.make_screen(key)
            screen.on_enter()
            text = plain(screen.body(ctx.surface))
            self.assertEqual(emoji_characters(text), [], key)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
