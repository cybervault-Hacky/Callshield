"""Phase 8.5: settings screen, preference persistence and reset scope."""

import json
import os
import unittest

from callshield.config import load_config
from callshield.ui.navigation import keys as K
from callshield.ui.state.preferences import (
    APPEARANCE_CHOICES,
    PreferencesStore,
    REFRESH_CHOICES,
    SCAN_MODE_CHOICES,
    UIPreferences,
    preferences_path,
)
from tests._common import IsolatedEnv
from tests._ui import make_app, render


class TestPreferencesStore(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.store = PreferencesStore(self.cfg)

    def tearDown(self):
        self.env.stop()

    def test_defaults(self):
        prefs = self.store.load()
        self.assertEqual(prefs.language, "en")
        self.assertEqual(prefs.appearance, "DARK")
        self.assertTrue(prefs.animation)
        self.assertEqual(prefs.refresh_seconds, 2)
        self.assertEqual(prefs.default_scan_mode, "BASIC")
        self.assertTrue(prefs.notifications)

    def test_round_trip(self):
        prefs = self.store.load()
        prefs.language = "hi"
        prefs.appearance = "LIGHT"
        prefs.refresh_seconds = 5
        self.assertTrue(self.store.save(prefs))
        again = PreferencesStore(self.cfg).load()
        self.assertEqual(again.language, "hi")
        self.assertEqual(again.appearance, "LIGHT")
        self.assertEqual(again.refresh_seconds, 5)

    def test_preferences_live_outside_the_security_config(self):
        path = preferences_path(self.cfg)
        self.assertTrue(path.endswith("ui_state.json"))
        from callshield import config as config_mod

        self.assertNotEqual(os.path.abspath(path),
                            os.path.abspath(str(config_mod.CONFIG_PATH)))

    def test_illegal_values_are_coerced(self):
        prefs = UIPreferences(
            language="klingon",
            appearance="NEON",
            refresh_seconds=999,
            default_scan_mode="TURBO",
        ).normalized()
        self.assertEqual(prefs.language, "en")
        self.assertIn(prefs.appearance, APPEARANCE_CHOICES)
        self.assertIn(prefs.refresh_seconds, REFRESH_CHOICES)
        self.assertIn(prefs.default_scan_mode, SCAN_MODE_CHOICES)

    def test_corrupted_file_falls_back_to_defaults(self):
        path = preferences_path(self.cfg)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json at all")
        prefs = self.store.load()
        self.assertTrue(self.store.recovered)
        self.assertEqual(prefs.language, "en")

    def test_non_object_file_falls_back_to_defaults(self):
        path = preferences_path(self.cfg)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([1, 2, 3], handle)
        prefs = self.store.load()
        self.assertTrue(self.store.recovered)
        self.assertEqual(prefs.appearance, "DARK")

    def test_unknown_fields_are_dropped(self):
        path = preferences_path(self.cfg)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"language": "fr", "root_password": "x"}, handle)
        prefs = self.store.load()
        self.assertEqual(prefs.language, "fr")
        self.assertFalse(hasattr(prefs, "root_password"))


class TestSettingsScreen(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def _settings(self, **kwargs):
        return make_app(self.cfg, screen_key="settings", **kwargs)

    def test_lists_every_required_entry(self):
        ctx, app = self._settings()
        text = render(app)
        for key in (
            "settings.language",
            "settings.appearance",
            "settings.animation",
            "settings.refresh",
            "settings.scan_mode",
            "settings.notifications",
            "settings.data",
            "settings.reset",
        ):
            self.assertIn(ctx.t(key), text)

    def test_toggle_animation_persists(self):
        ctx, app = self._settings()
        app.current.menu.select_index(2)
        app.handle_key(K.ENTER)
        self.assertFalse(ctx.prefs.animation)
        self.assertFalse(PreferencesStore(self.cfg).load().animation)

    def test_appearance_choice_screen_writes_preference(self):
        ctx, app = self._settings()
        app.handle_key("2")  # appearance
        self.assertEqual(app.stack.depth, 2)
        choice = app.current
        target = choice.menu.by_key("LIGHT")
        self.assertIsNotNone(target)
        choice.activate(target)
        self.assertEqual(ctx.prefs.appearance, "LIGHT")
        self.assertEqual(PreferencesStore(self.cfg).load().appearance, "LIGHT")

    def test_refresh_rate_offers_manual(self):
        ctx, app = self._settings()
        app.handle_key("4")  # refresh
        keys = [item.key for item in app.current.menu.items]
        self.assertEqual(keys, [str(value) for value in REFRESH_CHOICES])
        app.current.activate(app.current.menu.by_key("0"))
        self.assertEqual(ctx.prefs.refresh_seconds, 0)
        self.assertTrue(ctx.prefs.manual_refresh)
        self.assertEqual(ctx.refresh_seconds, 0.0)

    def test_default_scan_mode_choice(self):
        ctx, app = self._settings()
        app.handle_key("5")
        app.current.activate(app.current.menu.by_key("ADVANCED"))
        self.assertEqual(ctx.prefs.default_scan_mode, "ADVANCED")

    def test_data_screen_is_read_only_and_shows_paths(self):
        ctx, app = self._settings()
        app.handle_key("7")
        text = render(app)
        self.assertIn(ctx.t("settings.data.title"), text)
        self.assertIn("ui_state.json", text)
        self.assertIsNone(app.current.handle("x"))

    # ---------------------------------------------------------------- reset
    def test_reset_prompt_defaults_to_no(self):
        ctx, app = make_app(self.cfg, screen_key="settings", answers=[""])
        ctx.set_preference("language", "fr")
        app.current.rebuild()
        app.handle_key("8")
        self.assertEqual(ctx.asked[-1], ctx.t("settings.reset_prompt"))
        self.assertIn("[y/N]", ctx.asked[-1])
        self.assertEqual(ctx.prefs.language, "fr")

    def test_reset_confirmed_restores_defaults(self):
        ctx, app = make_app(self.cfg, screen_key="settings", answers=["y"])
        ctx.set_preference("language", "ja")
        ctx.set_preference("appearance", "LIGHT")
        app.current.rebuild()
        app.handle_key("8")
        self.assertEqual(ctx.prefs.language, "en")
        self.assertEqual(ctx.prefs.appearance, "DARK")

    def test_reset_touches_nothing_but_the_ui_state_file(self):
        from callshield import config as config_mod
        from tests._common import run_cli

        run_cli(self.cfg, "block", "+919876500011", "--reason", "test")
        run_cli(self.cfg, "report", "+919876500011", "--reason", "spam")

        with open(str(config_mod.CONFIG_PATH), "r", encoding="utf-8") as handle:
            config_before = handle.read()
        db_before = os.path.getsize(self.cfg.database_path)

        ctx, app = make_app(self.cfg, screen_key="settings", answers=["y"])
        app.handle_key("8")

        from callshield.database import Database

        db = Database(self.cfg.database_path)
        try:
            self.assertEqual(len(db.list_numbers("blacklist")), 1)
            self.assertEqual(db.count_reports("+919876500011"), 1)
        finally:
            db.close()

        with open(str(config_mod.CONFIG_PATH), "r", encoding="utf-8") as handle:
            config_after = handle.read()
        self.assertEqual(config_before, config_after)
        self.assertEqual(db_before, os.path.getsize(self.cfg.database_path))
        # Security configuration is untouched.
        reloaded = load_config()
        self.assertEqual(reloaded.screening_enabled, self.cfg.screening_enabled)
        self.assertEqual(reloaded.screening_mode, self.cfg.screening_mode)
        self.assertEqual(reloaded.protection_mode, self.cfg.protection_mode)

    def test_preferences_module_cannot_reach_security_state(self):
        import inspect

        from callshield.ui.state import preferences as prefs_mod

        source = inspect.getsource(prefs_mod)
        for forbidden in ("Database", "save_config", "set_value", "daemon",
                          "emergency", "screening"):
            self.assertNotIn(forbidden + "(", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
