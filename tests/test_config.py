import unittest

from callshield.config import Config, load_config, save_config, set_mode, set_value, set_profile
from callshield.intelligence.profiles import PROFILES
from callshield.utils import ConfigError
from tests._common import IsolatedEnv


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.path = self.env.data / "config.json"

    def tearDown(self):
        self.env.stop()

    def test_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.protection_mode, "BALANCED")
        self.assertEqual(cfg.risk_threshold, PROFILES["BALANCED"].risk_threshold)
        self.assertTrue(cfg.logging_enabled)
        self.assertEqual(cfg.color_enabled, "AUTO")

    def test_persistence_roundtrip(self):
        cfg = Config(default_country="US", risk_threshold=40)
        save_config(cfg, self.path)
        loaded = load_config(self.path)
        self.assertEqual(loaded.default_country, "US")
        self.assertEqual(loaded.risk_threshold, 40)

    def test_invalid_mode(self):
        with self.assertRaises(ConfigError):
            Config.from_dict({"protection_mode": "BOGUS"})

    def test_invalid_threshold(self):
        with self.assertRaises(ConfigError):
            Config.from_dict({"risk_threshold": 999})

    def test_set_profile_changes_threshold(self):
        cfg = set_profile(Config(), "strict")
        self.assertEqual(cfg.protection_mode, "STRICT")
        self.assertEqual(cfg.risk_threshold, PROFILES["STRICT"].risk_threshold)

    def test_set_mode_alias(self):
        cfg = set_mode(Config(), "relaxed")
        self.assertEqual(cfg.protection_mode, "RELAXED")

    def test_legacy_permissive_maps_to_relaxed(self):
        self.path.write_text('{"protection_mode":"PERMISSIVE"}', encoding="utf-8")
        cfg = load_config(self.path)
        self.assertEqual(cfg.protection_mode, "RELAXED")

    def test_set_value_unknown_key(self):
        with self.assertRaises(ConfigError):
            set_value(Config(), "not_a_key", "x")

    def test_ignores_unknown_keys_in_file(self):
        self.path.write_text('{"protection_mode":"RELAXED","random":123}', encoding="utf-8")
        cfg = load_config(self.path)
        self.assertEqual(cfg.protection_mode, "RELAXED")

    def test_corrupt_file_errors(self):
        self.path.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_config(self.path)

    def test_invalid_signal_weight_rejected(self):
        with self.assertRaises(ConfigError):
            set_value(Config(), "signal_weights", "blacklist_match=abc")


if __name__ == "__main__":
    unittest.main()
