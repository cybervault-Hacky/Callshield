"""Phase 8.5: translation catalogues, language switching and fallback."""

import unittest

from callshield.ui.i18n import (
    Translator,
    available_languages,
    language_label,
    missing_keys,
    normalize_language,
)
from callshield.ui.i18n.catalog import (
    CATALOGS,
    DEFAULT_LANGUAGE,
    EN,
    LANGUAGES,
    UNTRANSLATED_KEYS,
)
from tests._common import IsolatedEnv
from tests._ui import emoji_characters, make_app, render

REQUIRED = ("en", "hi", "hinglish", "es", "fr", "ja", "zh", "pt", "ru")

# Technical command names that must never be translated.
COMMANDS = (
    "callshield",
    "scan",
    "status",
    "metrics",
    "doctor",
    "daemon",
    "reputation",
    "intelligence",
    "screening",
    "policy",
    "blocks",
)


class TestCatalogs(unittest.TestCase):
    def test_all_nine_languages_present(self):
        for code in REQUIRED:
            self.assertIn(code, LANGUAGES, code)
            self.assertIn(code, CATALOGS, code)

    def test_english_is_the_default(self):
        self.assertEqual(DEFAULT_LANGUAGE, "en")

    def test_translations_are_complete(self):
        for code in LANGUAGES:
            missing = set(missing_keys(code)) - set(UNTRANSLATED_KEYS)
            self.assertEqual(missing, set(), "%s missing %s" % (code, sorted(missing)))

    def test_no_catalog_defines_unknown_keys(self):
        for code, catalog in CATALOGS.items():
            extra = set(catalog) - set(EN)
            self.assertEqual(extra, set(), "%s has stray keys %s" % (code, extra))

    def test_no_emoji_in_any_catalog(self):
        for code, catalog in CATALOGS.items():
            for key, value in catalog.items():
                self.assertEqual(emoji_characters(value), [],
                                 "%s/%s: %r" % (code, key, value))

    def test_technical_command_names_are_not_translated(self):
        for code, catalog in CATALOGS.items():
            for key, english in EN.items():
                for command in COMMANDS:
                    token = "`{0}".format(command)
                    if token in english:
                        self.assertIn(token, catalog.get(key, english),
                                      "%s/%s dropped %s" % (code, key, command))

    def test_format_placeholders_survive_translation(self):
        import re

        pattern = re.compile(r"\{([a-z_]+)\}")
        for code, catalog in CATALOGS.items():
            for key, english in EN.items():
                expected = set(pattern.findall(english))
                actual = set(pattern.findall(catalog.get(key, english)))
                self.assertEqual(expected, actual, "%s/%s" % (code, key))


class TestTranslator(unittest.TestCase):
    def test_lookup(self):
        self.assertEqual(Translator("en").text("nav.quit"), EN["nav.quit"])

    def test_unknown_language_falls_back_to_english(self):
        translator = Translator("klingon")
        self.assertEqual(translator.language, "en")

    def test_missing_key_falls_back_to_english_then_to_the_key(self):
        translator = Translator("hi")
        self.assertEqual(translator.text("app.title"), EN["app.title"])
        self.assertEqual(translator.text("no.such.key"), "no.such.key")

    def test_bad_format_fields_do_not_raise(self):
        translator = Translator("en")
        self.assertTrue(translator.text("history.page"))
        self.assertTrue(translator.text("history.page", wrong=1))

    def test_regional_tags_are_accepted(self):
        self.assertEqual(normalize_language("pt-BR"), "pt")
        self.assertEqual(normalize_language("es-MX"), "es")
        self.assertEqual(normalize_language("Hinglish"), "hinglish")

    def test_labels_and_listing(self):
        codes = [code for code, _label in available_languages()]
        self.assertEqual(codes, list(LANGUAGES))
        self.assertTrue(language_label("ja"))

    def test_non_string_language_is_safe(self):
        self.assertEqual(normalize_language(None), "en")
        self.assertEqual(normalize_language(7), "en")


class TestLanguageSwitching(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_switching_language_changes_the_rendered_interface(self):
        ctx, app = make_app(self.cfg, screen_key="settings")
        english = render(app)
        ctx.set_preference("language", "es")
        app.current.rebuild()
        spanish = render(app)
        self.assertNotEqual(english, spanish)
        self.assertIn(ctx.t("settings.title"), spanish)

    def test_language_screen_lists_every_language(self):
        ctx, app = make_app(self.cfg, screen_key="settings")
        app.handle_key("1")
        keys = [item.key for item in app.current.menu.items]
        self.assertEqual(keys, list(LANGUAGES))

    def test_selecting_a_language_persists_it(self):
        from callshield.ui.state.preferences import PreferencesStore

        ctx, app = make_app(self.cfg, screen_key="settings")
        app.handle_key("1")
        app.current.activate(app.current.menu.by_key("ja"))
        self.assertEqual(ctx.prefs.language, "ja")
        self.assertEqual(PreferencesStore(self.cfg).load().language, "ja")

    def test_every_screen_renders_in_every_language(self):
        from callshield.ui.screens import REGISTRY

        ctx, _app = make_app(self.cfg)
        for code in LANGUAGES:
            ctx.set_preference("language", code)
            for key in REGISTRY:
                screen = ctx.make_screen(key)
                screen.on_enter()
                lines = screen.body(ctx.surface)
                self.assertTrue(all(isinstance(line, str) for line in lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
