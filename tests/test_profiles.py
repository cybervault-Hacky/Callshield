import unittest

from callshield.config import Config, set_profile, set_value
from callshield.intelligence.profiles import PROFILES, get_profile
from callshield.utils import ConfigError
from tests._common import IsolatedEnv


class TestProfiles(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()

    def tearDown(self):
        self.env.stop()

    def test_default_is_balanced(self):
        cfg = Config()
        self.assertEqual(cfg.protection_mode, "BALANCED")

    def test_relaxed_higher_threshold(self):
        p = get_profile("RELAXED")
        b = get_profile("BALANCED")
        self.assertGreaterEqual(p.risk_threshold, b.risk_threshold)

    def test_strict_lower_threshold(self):
        s = get_profile("STRICT")
        b = get_profile("BALANCED")
        self.assertLessEqual(s.risk_threshold, b.risk_threshold)

    def test_set_profile_cycle(self):
        cfg = Config()
        for name in ("relaxed", "balanced", "strict"):
            cfg = set_profile(cfg, name)
            self.assertEqual(cfg.protection_mode, name.upper())

    def test_unknown_profile_rejected(self):
        with self.assertRaises(KeyError):
            get_profile("BOGUS")

    def test_permissive_alias_is_relaxed(self):
        cfg = set_value(Config(), "profile", "permissive")
        self.assertEqual(cfg.protection_mode, "RELAXED")


if __name__ == "__main__":
    unittest.main()
