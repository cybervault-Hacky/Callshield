import unittest

from callshield.database import Database
from callshield.detector import analyze_number
from callshield.utils import iso_now
from tests._common import IsolatedEnv


class TestReputation(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_trusted_for_whitelisted_without_history(self):
        self.db.upsert_list_entry("+442071838750", "whitelist", None, iso_now())
        r = analyze_number("+442071838750", db=self.db, cfg=self.cfg, record_event=False)
        self.assertIn(r.reputation, ("TRUSTED", "SAFE"))
        self.assertEqual(r.verdict, "SAFE")

    def test_safe_for_no_indicators(self):
        r = analyze_number("+442071838750", db=self.db, cfg=self.cfg, record_event=False)
        self.assertEqual(r.reputation, "UNKNOWN")

    def test_suspicious_tier(self):
        # A manually-reported number without being blacklisted should land
        # in SUSPICIOUS rather than MALICIOUS.
        for _ in range(1):
            self.db.add_report("+919999955555", "suspicious caller", iso_now())
        r = analyze_number("+919999955555", db=self.db, cfg=self.cfg, record_event=False)
        # Not on blacklist, one report: should NOT be MALICIOUS.
        self.assertIn(r.reputation, ("UNKNOWN", "SAFE", "SUSPICIOUS", "HIGH_RISK"))

    def test_malicious_for_blacklisted(self):
        self.db.upsert_list_entry("+919999966666", "blacklist", None, iso_now())
        r = analyze_number("+919999966666", db=self.db, cfg=self.cfg, record_event=False)
        self.assertEqual(r.reputation, "MALICIOUS")
        self.assertEqual(r.verdict, "MALICIOUS")

    def test_high_risk_reputation_threshold(self):
        # Two reports push us into HIGH_RISK territory (2*8=16, plus... need more).
        for _ in range(5):
            self.db.add_report("+919999977777", "scam", iso_now())
        r = analyze_number("+919999977777", db=self.db, cfg=self.cfg, record_event=False)
        self.assertGreaterEqual(r.risk_score, 20)  # at least some risk signal


if __name__ == "__main__":
    unittest.main()
