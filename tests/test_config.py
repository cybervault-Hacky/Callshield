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

    def test_corrupt_file_fails_safe_and_strict_mode_errors(self):
        self.path.write_text("{not valid json", encoding="utf-8")
        cfg = load_config(self.path)
        self.assertFalse(cfg.screening_enabled)
        self.assertEqual(cfg.screening_mode, "DRY_RUN")
        self.assertFalse(cfg.active_mode_confirmed)
        self.assertTrue(getattr(cfg, "_config_integrity_error", None))
        with self.assertRaises(ConfigError):
            load_config(self.path, strict=True)

    def test_invalid_signal_weight_rejected(self):
        with self.assertRaises(ConfigError):
            set_value(Config(), "signal_weights", "blacklist_match=abc")

    def test_phase3_resource_defaults(self):
        cfg = Config()
        self.assertEqual(cfg.event_queue_size, 256)
        self.assertEqual(cfg.heartbeat_interval, 30)
        self.assertEqual(cfg.event_payload_limit, 8 * 1024)
        self.assertGreater(cfg.ipc_timeout, 0)
        self.assertEqual(cfg.socket_path.rsplit("/", 1)[-1], "callshield.sock")

    def test_phase3_bounds_rejected(self):
        for values in (
            {"event_queue_size": 0},
            {"heartbeat_interval": 0},
            {"ipc_timeout": 0},
            {"event_payload_limit": 128},
            {"status_refresh_interval": 99},
        ):
            with self.subTest(values=values), self.assertRaises(ConfigError):
                Config.from_dict(values)

    def test_phase3_config_aliases(self):
        cfg = Config.from_dict(
            {
                "queue_size": 64,
                "watch_interval": 3,
                "daemon_socket": "/tmp/callshield-alias.sock",
                "daemon_pid_file": "/tmp/callshield-alias.pid",
            }
        )
        self.assertEqual(cfg.event_queue_size, 64)
        self.assertEqual(cfg.status_refresh_interval, 3)
        self.assertEqual(cfg.socket_path, "/tmp/callshield-alias.sock")
        self.assertEqual(cfg.pid_file, "/tmp/callshield-alias.pid")

    def test_set_phase3_timeout_and_payload_limit(self):
        cfg = set_value(Config(), "ipc_timeout", "1.5")
        cfg = set_value(cfg, "event_payload_limit", "4096")
        self.assertEqual(cfg.ipc_timeout, 1.5)
        self.assertEqual(cfg.event_payload_limit, 4096)


if __name__ == "__main__":
    unittest.main()
