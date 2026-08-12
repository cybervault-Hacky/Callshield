"""Phase 8.5: failure handling, graceful degradation and the local-only audit.

Every test here drives the interface into a broken state on purpose — no
daemon, an unreadable database, a corrupted preferences file, a two-column
terminal, an interrupted prompt — and asserts that the user still gets a
labelled message and a way out instead of a traceback.
"""

import ast
import io
import os
import unittest
from pathlib import Path

from callshield.ui import app as app_mod
from callshield.ui.app import AppContext, Application
from callshield.ui.navigation import keys as K
from callshield.ui.screens import REGISTRY
from callshield.ui.state.backend import Backend, Result
from callshield.ui.state.preferences import PreferencesStore, preferences_path
from tests._common import IsolatedEnv, run_cli
from tests._ui import ScriptedContext, caps, make_app, plain, render

UI_ROOT = Path(__file__).resolve().parents[1] / "callshield/ui"


class UIErrorCase(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()


# --------------------------------------------------------------- daemon down
class TestDaemonUnavailable(UIErrorCase):
    def test_backend_reports_offline_without_raising(self):
        backend = Backend(self.cfg)
        state, _pid = backend.daemon_state()
        self.assertIn(state, ("STOPPED", "STALE", "UNKNOWN"))
        self.assertFalse(backend.daemon_online())

        health = backend.daemon_health()
        self.assertFalse(health.ok)
        self.assertTrue(health.error)

        info = backend.daemon_info()
        self.assertFalse(info.ok)

    def test_metrics_fall_back_to_stored_values(self):
        run_cli(self.cfg, "scan", "+919876511001")
        metrics = Backend(self.cfg).daemon_metrics()
        self.assertTrue(metrics.ok)
        self.assertEqual(metrics.source, "offline")
        self.assertGreaterEqual(int(metrics.get("received") or 0), 1)

    def test_daemon_screen_labels_the_outage(self):
        ctx, app = make_app(self.cfg, screen_key="daemon",
                            caps=caps(width=100, height=60))
        text = render(app)
        self.assertIn(ctx.t("daemon.not_running"), text)
        # The screen still offers a way to start it.
        self.assertIn(ctx.t("daemon.start"), text)

    def test_health_action_is_refused_politely_when_stopped(self):
        ctx, app = make_app(self.cfg, screen_key="daemon")
        app.current.activate(app.current.menu.by_key("health"))
        self.assertIn(ctx.t("daemon.not_running"), render(app))
        self.assertEqual(app.stack.depth, 1)

    def test_ipc_call_without_socket_is_an_error_not_a_crash(self):
        result = Backend(self.cfg).ipc("screening_status")
        self.assertFalse(result.ok)
        self.assertEqual(result.source, "ipc")


# ------------------------------------------------------------ database down
class TestDatabaseUnavailable(UIErrorCase):
    def _break_database(self):
        with open(self.cfg.database_path, "wb") as handle:
            handle.write(b"this is not a sqlite database" * 32)

    def test_queries_return_errors(self):
        self._break_database()
        backend = Backend(self.cfg)
        for result in (backend.event_metrics(),
                       backend.recent_events(limit=5),
                       backend.screening_metrics()):
            self.assertFalse(result.ok)
            self.assertTrue(result.error)

    def test_dashboard_still_renders(self):
        self._break_database()
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=70))
        text = render(app)
        self.assertIn("CALLSHIELD", text)
        self.assertIn("ERROR", text)

    def test_history_screen_reports_the_failure(self):
        self._break_database()
        ctx, app = make_app(self.cfg, screen_key="history")
        self.assertTrue(app.current.message)
        self.assertEqual(app.current.level, "err")

    def test_every_screen_survives_a_broken_database(self):
        self._break_database()
        ctx, _app = make_app(self.cfg)
        for key in REGISTRY:
            screen = ctx.make_screen(key)
            self.assertIsNotNone(screen, key)
            screen.on_enter()
            lines = screen.body(ctx.surface)
            self.assertIsInstance(lines, list, key)


# ------------------------------------------------------- corrupted UI state
class TestCorruptedUIState(UIErrorCase):
    def test_unparsable_file_recovers_to_defaults(self):
        with open(preferences_path(self.cfg), "w", encoding="utf-8") as handle:
            handle.write("<<<not json>>>")
        ctx = ScriptedContext(self.cfg)
        self.assertEqual(ctx.prefs.language, "en")
        self.assertEqual(ctx.startup_notice, "error.corrupt_config")

    def test_notice_is_shown_once_and_is_labelled(self):
        with open(preferences_path(self.cfg), "w", encoding="utf-8") as handle:
            handle.write("{oops")
        ctx = ScriptedContext(self.cfg)
        app = Application(ctx)
        app.start(ctx.make_screen("dashboard"))
        app.current.set_message(ctx.t(ctx.startup_notice), "warn")
        self.assertIn("WARNING", render(app))

    def test_hostile_values_cannot_escape_the_allowed_set(self):
        with open(preferences_path(self.cfg), "w", encoding="utf-8") as handle:
            handle.write(
                '{"language": "../../etc/passwd", "appearance": "$(id)",'
                ' "refresh_seconds": -99999, "default_scan_mode": true}'
            )
        prefs = PreferencesStore(self.cfg).load()
        self.assertEqual(prefs.language, "en")
        self.assertEqual(prefs.appearance, "DARK")
        self.assertEqual(prefs.refresh_seconds, 2)
        self.assertEqual(prefs.default_scan_mode, "BASIC")

    def test_unwritable_state_file_does_not_crash_the_settings_screen(self):
        path = preferences_path(self.cfg)
        directory = os.path.dirname(path)
        ctx, app = make_app(self.cfg, screen_key="settings")
        os.chmod(directory, 0o500)
        try:
            saved = ctx.set_preference("appearance", "LIGHT")
        finally:
            os.chmod(directory, 0o700)
        # Either the write failed cleanly (False) or the platform allowed it;
        # in both cases nothing raised and the screen still renders.
        self.assertIn(saved, (True, False))
        self.assertIn("CALLSHIELD", render(app))

    def test_oversized_state_file_is_rejected(self):
        with open(preferences_path(self.cfg), "w", encoding="utf-8") as handle:
            handle.write('{"language": "fr", "pad": "' + "x" * 70000 + '"}')
        store = PreferencesStore(self.cfg)
        prefs = store.load()
        self.assertTrue(store.recovered)
        self.assertEqual(prefs.language, "en")


# ------------------------------------------------------------- bad input
class TestInvalidInput(UIErrorCase):
    def test_invalid_number_is_labelled_on_every_prompt_screen(self):
        for key, item in (("blocks", "add_block"), ("reports", "submit"),
                          ("history", "number"), ("reputation", "lookup"),
                          ("intelligence", "search")):
            ctx, app = make_app(self.cfg, screen_key=key,
                                answers=["not-a-number", "reason", "y"])
            app.current.activate(app.current.menu.by_key(item))
            self.assertEqual(app.current.message,
                             ctx.t("prompt.invalid_number"), key)

    def test_empty_input_cancels_instead_of_guessing(self):
        ctx, app = make_app(self.cfg, screen_key="scan", answers=[""])
        app.handle_key("1")
        self.assertEqual(app.stack.depth, 1)
        self.assertIn(ctx.t("prompt.empty_input"), render(app))

    def test_out_of_range_policy_values_are_rejected(self):
        ctx, app = make_app(self.cfg, screen_key="policy",
                            answers=["9000", "50"])
        app.current.activate(app.current.menu.by_key("test"))
        self.assertEqual(app.stack.depth, 1)
        self.assertEqual(app.current.message, ctx.t("prompt.invalid_choice"))

    def test_non_numeric_block_id_is_rejected(self):
        ctx, app = make_app(self.cfg, screen_key="blocks", answers=["abc"])
        item = app.current.menu.by_key("inspect")
        app.current.activate(item)
        self.assertEqual(app.current.message, ctx.t("prompt.invalid_choice"))

    def test_backend_rejects_a_bad_decision_id(self):
        result = Backend(self.cfg).inspect_block("not-an-id")
        self.assertFalse(result.ok)

    def test_backend_rejects_an_unknown_list(self):
        self.assertFalse(Backend(self.cfg).list_numbers("secrets").ok)


# ------------------------------------------------------- interrupted input
class TestInterruption(UIErrorCase):
    def test_ctrl_c_at_a_prompt_returns_to_the_screen(self):
        ctx, app = make_app(self.cfg, screen_key="scan",
                            answers=[KeyboardInterrupt()])
        with self.assertRaises(KeyboardInterrupt):
            app.current.activate(app.current.menu.by_key("basic"))
        # The stack is untouched: the user is still on the Scan Center.
        self.assertEqual(app.stack.depth, 1)

    def test_ctrl_c_key_exits_the_loop_cleanly(self):
        ctx, app = make_app(self.cfg)
        self.assertFalse(app.handle_key(K.INTERRUPT))
        self.assertEqual(app.exit_code, 0)

    def test_screen_raising_keyboard_interrupt_stops_the_loop(self):
        ctx, app = make_app(self.cfg)

        def explode(_key):
            raise KeyboardInterrupt()

        app.current.handle = explode
        self.assertFalse(app.handle_key("x"))

    def test_esc_at_the_root_exits_rather_than_trapping(self):
        ctx, app = make_app(self.cfg)
        self.assertEqual(app.stack.depth, 1)
        self.assertFalse(app.handle_key(K.ESC))

    def test_esc_from_a_child_screen_goes_back(self):
        ctx, app = make_app(self.cfg, screen_key="settings")
        app.handle_key("7")  # Data
        self.assertEqual(app.stack.depth, 2)
        self.assertTrue(app.handle_key(K.ESC))
        self.assertEqual(app.stack.depth, 1)

    def test_a_screen_that_raises_becomes_a_message_not_a_crash(self):
        ctx, app = make_app(self.cfg)

        def explode(_surface):
            raise RuntimeError("body exploded")

        app.current.body = explode
        text = render(app)
        self.assertIn("ERROR", text)

    def test_a_refresh_that_raises_is_reported(self):
        ctx, app = make_app(self.cfg)

        def explode():
            raise RuntimeError("refresh exploded")

        app.current.refresh = explode
        app.refresh_current()
        self.assertEqual(app.current.level, "err")
        self.assertIn("refresh exploded", app.current.message)


# ----------------------------------------------------------------- layout
class TestResizeAndNarrowTerminals(UIErrorCase):
    def test_resize_rebuilds_the_surface(self):
        ctx, app = make_app(self.cfg, caps=caps(width=100, height=40))
        self.assertEqual(ctx.surface.width, 100)
        ctx.resize(ctx.caps.replace(width=52, height=18))
        self.assertEqual(ctx.surface.width, 52)
        for line in app.render():
            self.assertLessEqual(len(line), 200)

    def test_narrow_terminal_still_renders_the_dashboard(self):
        ctx, app = make_app(self.cfg, caps=caps(width=46, height=20))
        text = render(app)
        self.assertIn("CALLSHIELD", text)
        for line in text.split("\n"):
            self.assertLessEqual(len(line), 46)

    def test_tiny_terminal_asks_for_more_room_and_keeps_quit_available(self):
        ctx, app = make_app(self.cfg, caps=caps(width=20, height=8))
        text = render(app)
        self.assertIn("WARNING", text)
        self.assertIn(ctx.t("nav.quit"), text)

    def test_frame_never_exceeds_the_terminal_height(self):
        for height in (12, 20, 32, 60):
            ctx, app = make_app(self.cfg, caps=caps(width=90, height=height))
            self.assertLessEqual(len(app.render()), height, height)

    def test_wide_terminal_does_not_overflow(self):
        ctx, app = make_app(self.cfg, caps=caps(width=200, height=50))
        for line in plain(app.render()).split("\n"):
            self.assertLessEqual(len(line), 200)

    def test_every_screen_fits_at_every_tested_width(self):
        for width in (40, 64, 100, 160):
            ctx, app = make_app(self.cfg, caps=caps(width=width, height=30))
            for key in REGISTRY:
                screen = ctx.make_screen(key)
                screen.on_enter()
                app.stack.push(screen, screen.title())
                for line in plain(app.render()).split("\n"):
                    self.assertLessEqual(len(line), width, (key, width))
                app.stack.pop()


# ------------------------------------------------------ non-interactive use
class TestNonInteractiveFallback(UIErrorCase):
    def test_summary_is_short_and_points_at_help(self):
        ctx = ScriptedContext(self.cfg, caps=caps(interactive=False))
        lines = app_mod.non_interactive_lines(ctx)
        text = plain(lines)
        self.assertLessEqual(len(lines), 20)
        self.assertIn("callshield --help", text)
        self.assertIn("CALLSHIELD", text)

    def test_run_does_not_start_the_loop_without_a_terminal(self):
        out = io.StringIO()
        ctx = AppContext(self.cfg, caps=caps(interactive=False), stdout=out)
        code = app_mod.run(self.cfg, ctx=ctx)
        self.assertEqual(code, 0)
        self.assertIn("callshield --help", out.getvalue())

    def test_bare_cli_without_a_tty_prints_the_banner(self):
        import contextlib

        from callshield import cli

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), \
                contextlib.redirect_stderr(buffer):
            code = cli.main([])
        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("CALLSHIELD", output)
        self.assertIn("callshield --help", output)

    def test_ui_can_be_disabled_by_environment(self):
        from callshield import cli

        os.environ["CALLSHIELD_NO_UI"] = "1"
        try:
            self.assertTrue(cli._ui_disabled())
        finally:
            os.environ.pop("CALLSHIELD_NO_UI", None)
        self.assertFalse(cli._ui_disabled())

    def test_prompts_return_none_without_a_terminal(self):
        ctx = AppContext(self.cfg, caps=caps(interactive=False),
                         stdout=io.StringIO())
        self.assertIsNone(ctx.ask("Number?"))
        self.assertFalse(ctx.confirm("Do the dangerous thing? [y/N] "))


# ---------------------------------------------------------- degraded output
class TestDegradedTerminals(UIErrorCase):
    def test_no_colour_output_has_no_escape_sequences(self):
        ctx, app = make_app(self.cfg, caps=caps(color=False, width=100,
                                                height=40))
        for key in REGISTRY:
            screen = ctx.make_screen(key)
            screen.on_enter()
            for line in screen.body(ctx.surface):
                self.assertNotIn("\x1b[", line, key)

    def test_ascii_only_terminal_avoids_box_drawing(self):
        ctx, app = make_app(self.cfg, caps=caps(unicode=False, width=90,
                                                height=40))
        for key in REGISTRY:
            screen = ctx.make_screen(key)
            screen.on_enter()
            text = plain(screen.body(ctx.surface))
            self.assertTrue(text.isprintable() or "\n" in text, key)
            for char in ("\u2500", "\u2502", "\u250c", "\u25b8"):
                self.assertNotIn(char, text, key)

    def test_closed_stdout_does_not_raise(self):
        stream = io.StringIO()
        ctx = ScriptedContext(self.cfg, stdout=stream)
        stream.close()
        ctx.write("anything")  # must be swallowed
        ctx.draw(["line"])

    def test_status_is_carried_by_words_not_colour(self):
        ctx, app = make_app(self.cfg, caps=caps(color=False, width=100,
                                                height=70))
        text = render(app)
        self.assertTrue(
            any(word in text for word in
                ("READY", "ERROR", "OFFLINE", "STOPPED", "DISABLED",
                 "NOT VERIFIED"))
        )


# ------------------------------------------------------------ local only
class TestNoNetworkAndNoDangerousApis(unittest.TestCase):
    def _sources(self):
        for path in sorted(UI_ROOT.rglob("*.py")):
            yield path, ast.parse(path.read_text(encoding="utf-8"),
                                  filename=str(path))

    def test_no_network_library_is_imported(self):
        forbidden = {
            "socket", "ssl", "requests", "urllib", "urllib2", "urllib3",
            "httpx", "http", "ftplib", "telnetlib", "smtplib", "dns",
            "xmlrpc", "asyncio", "websocket", "websockets", "aiohttp",
        }
        violations = []
        for path, tree in self._sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] in forbidden:
                            violations.append((path.name, node.lineno,
                                               alias.name))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.split(".")[0] in forbidden:
                        violations.append((path.name, node.lineno,
                                           node.module))
        self.assertEqual(violations, [])

    def test_no_dangerous_execution_or_deserialisation(self):
        violations = []
        for path, tree in self._sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in (
                        "eval", "exec", "compile", "__import__"
                    ):
                        violations.append((path.name, node.lineno,
                                           node.func.id))
                    if isinstance(node.func, ast.Attribute):
                        owner = getattr(node.func.value, "id", "")
                        if owner in ("os", "subprocess", "pickle", "marshal"):
                            if node.func.attr in (
                                "system", "popen", "spawn", "spawnl", "spawnv",
                                "execv", "execl", "loads", "load", "dumps",
                                "Popen", "call", "run", "check_output",
                            ):
                                violations.append(
                                    (path.name, node.lineno,
                                     owner + "." + node.func.attr)
                                )
                    for keyword in node.keywords:
                        if (keyword.arg == "shell"
                                and isinstance(keyword.value, ast.Constant)
                                and keyword.value.value is True):
                            violations.append((path.name, node.lineno,
                                               "shell=True"))
                if isinstance(node, ast.Attribute) and node.attr in (
                    "AF_INET", "AF_INET6"
                ):
                    violations.append((path.name, node.lineno, node.attr))
        self.assertEqual(violations, [])

    def test_no_hardcoded_urls_or_hosts(self):
        for path in sorted(UI_ROOT.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for token in ("http://", "https://", "ftp://", "0.0.0.0",
                          "127.0.0.1"):
                self.assertNotIn(token, text, path.name)

    def test_ui_never_writes_the_security_config(self):
        """Only the CLI handlers may persist configuration."""

        for path in sorted(UI_ROOT.rglob("*.py")):
            if path.name == "backend.py":
                continue  # delegates to CLI handlers, audited separately
            text = path.read_text(encoding="utf-8")
            for forbidden in ("save_config(", "set_value(", "set_profile(",
                              "enable_emergency_off(", "reset_emergency_off("):
                self.assertNotIn(forbidden, text, path.name)

    def test_backend_delegates_mutations_to_cli_handlers(self):
        source = (UI_ROOT / "state/backend.py").read_text(encoding="utf-8")
        # Configuration changes go through the CLI command table, never
        # through direct writes.
        self.assertIn("_cli._COMMANDS", source)
        self.assertNotIn("save_config(", source)
        self.assertNotIn("cfg.screening_mode =", source)
        self.assertNotIn("cfg.screening_enabled =", source)

    def test_no_third_party_dependency_is_imported(self):
        allowed_first_party = {"callshield", ""}
        stdlib_ok = {
            "abc", "ast", "collections", "contextlib", "dataclasses",
            "datetime", "enum", "errno", "fcntl", "io", "itertools", "json",
            "locale", "math", "os", "pathlib", "re", "select", "shutil",
            "signal", "string", "sys", "termios", "textwrap", "time", "tty",
            "types", "typing", "unicodedata", "uuid", "warnings", "importlib",
            "__future__",
        }
        violations = []
        for path, tree in self._sources():
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root not in stdlib_ok | allowed_first_party:
                            violations.append((path.name, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import inside callshield
                        continue
                    root = (node.module or "").split(".")[0]
                    if root not in stdlib_ok | allowed_first_party:
                        violations.append((path.name, node.module))
        self.assertEqual(violations, [])


# ------------------------------------------------------------ safety rails
class TestSafetyRails(UIErrorCase):
    def test_policy_simulation_never_writes_configuration(self):
        from callshield.config import load_config

        before = load_config()
        result = Backend(self.cfg).policy_simulate(99, 99, mode="ACTIVE",
                                                   policy_name="STRICT")
        self.assertTrue(result.ok)
        self.assertTrue(getattr(result.data, "simulation", False))
        after = load_config()
        self.assertEqual(before.screening_mode, after.screening_mode)
        self.assertEqual(before.screening_policy, after.screening_policy)
        self.assertEqual(before.active_mode_confirmed,
                         after.active_mode_confirmed)

    def test_active_mode_cannot_be_set_without_the_cli_prompt(self):
        result = Backend(self.cfg).set_screening_mode("active")
        self.assertFalse(result.ok)
        from callshield.config import load_config

        self.assertNotEqual(load_config().screening_mode, "ACTIVE")

    def test_enable_screening_forces_dry_run(self):
        from callshield.config import load_config

        result = Backend(self.cfg).set_screening_enabled(True)
        self.assertTrue(result.ok)
        reloaded = load_config()
        self.assertEqual(reloaded.screening_mode, "DRY_RUN")
        self.assertFalse(reloaded.active_mode_confirmed)

    def test_emergency_control_is_reachable_from_the_policy_screen(self):
        ctx, app = make_app(self.cfg, screen_key="policy")
        keys = [item.key for item in app.current.menu.items]
        self.assertTrue("emergency" in keys or "emergency_reset" in keys)

    def test_destructive_actions_all_confirm_first(self):
        for key, item in (("daemon", "stop"), ("blocks", "add_block"),
                          ("policy", "emergency"), ("settings", "reset")):
            ctx, app = make_app(self.cfg, screen_key=key,
                                answers=["+919876511222", ""])
            app.current.activate(app.current.menu.by_key(item))
            self.assertTrue(any("[y/N]" in question for question in ctx.asked),
                            key)

    def test_numbers_are_masked_in_every_rendered_screen(self):
        number = "+919876511333"
        run_cli(self.cfg, "scan", number)
        run_cli(self.cfg, "block", number, "--reason", "test")
        ctx, _app = make_app(self.cfg, caps=caps(width=120, height=60))
        for key in REGISTRY:
            screen = ctx.make_screen(key)
            screen.on_enter()
            self.assertNotIn(number, plain(screen.body(ctx.surface)), key)

    def test_result_helper_is_defensive(self):
        empty = Result()
        self.assertTrue(empty.ok)
        self.assertIsNone(empty.get("missing"))
        failed = Result(error="boom", source="database")
        self.assertFalse(failed.ok)
        self.assertEqual(failed.get("anything", "default"), "default")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
