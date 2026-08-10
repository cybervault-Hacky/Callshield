import unittest

from callshield.database import Database
from callshield.detector import analyze_number
from callshield.utils import InvalidNumberError, iso_now
from tests._common import IsolatedEnv


# Use a well-formed number that does not trigger weak pattern signals.
SAFE_NUM = "+442071838750"     # UK number, no obvious pattern.
BLOCKED_NUM = "+919999911111" # Will be blacklisted.
TRUSTED_NUM = "+919999922222" # Will be whitelisted.


class TestDetector(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_unknown_number_returns_unknown(self):
        r = analyze_number(SAFE_NUM, db=self.db, cfg=self.cfg, record_event=False)
        self.assertEqual(r.verdict, "UNKNOWN")
        self.assertEqual(r.recommended_action, "ALLOW")
        self.assertEqual(r.risk_score, 0)
        self.assertEqual(r.reputation, "UNKNOWN")

    def test_blocked_number_is_malicious(self):
        self.db.upsert_list_entry(BLOCKED_NUM, "blacklist", None, iso_now())
        r = analyze_number(BLOCKED_NUM, db=self.db, cfg=self.cfg, record_event=False)
        # Explicit blacklist yields MALICIOUS (Phase 2 upgrade from HIGH_RISK).
        self.assertIn(r.verdict, ("HIGH_RISK", "MALICIOUS"))
        self.assertEqual(r.recommended_action, "BLOCK")
        self.assertGreaterEqual(r.risk_score, 80)

    def test_whitelisted_number_is_safe(self):
        self.db.upsert_list_entry(TRUSTED_NUM, "whitelist", None, iso_now())
        r = analyze_number(TRUSTED_NUM, db=self.db, cfg=self.cfg, record_event=False)
        self.assertEqual(r.verdict, "SAFE")
        self.assertEqual(r.recommended_action, "ALLOW")
        self.assertEqual(r.risk_score, 0)
        self.assertIn(r.reputation, ("SAFE", "TRUSTED"))

    def test_whitelist_overrides_blacklist_conflict(self):
        n = "+919988877777"
        self.db.upsert_list_entry(n, "blacklist", None, iso_now())
        self.db.upsert_list_entry(n, "whitelist", None, iso_now())
        r = analyze_number(n, db=self.db, cfg=self.cfg, record_event=False)
        self.assertTrue(r.list_conflict)
        self.assertEqual(r.verdict, "SAFE")
        self.assertEqual(r.recommended_action, "ALLOW")

    def test_invalid_number_raises(self):
        with self.assertRaises(InvalidNumberError):
            analyze_number("not-a-number", db=self.db, cfg=self.cfg, record_event=False)

    def test_event_logged_when_enabled(self):
        before = len(self.db.recent_events(1000))
        analyze_number(SAFE_NUM, db=self.db, cfg=self.cfg, record_event=True)
        after = len(self.db.recent_events(1000))
        self.assertEqual(after, before + 1)

    def test_safe_number_low_score(self):
        self.db.upsert_list_entry(SAFE_NUM, "whitelist", None, iso_now())
        r = analyze_number(SAFE_NUM, db=self.db, cfg=self.cfg, record_event=False)
        self.assertEqual(r.verdict, "SAFE")
        self.assertEqual(r.risk_score, 0)

    def test_result_is_dict_serializable(self):
        r = analyze_number(SAFE_NUM, db=self.db, cfg=self.cfg, record_event=False)
        d = r.to_dict()
        self.assertEqual(d["number"], SAFE_NUM)
        self.assertIn("risk_score", d)
        self.assertIn("confidence", d)
        self.assertIn("signals", d)
        self.assertIn("behavior", d)
        self.assertIn("number_intelligence", d)


if __name__ == "__main__":
    unittest.main()
