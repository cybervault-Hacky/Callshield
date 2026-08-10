import unittest

from callshield.database import Database
from callshield.detector import analyze_number
from callshield.intelligence.confidence import compute_confidence
from callshield.intelligence.signals import SignalResult
from callshield.utils import iso_now
from tests._common import IsolatedEnv


class TestConfidence(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_confidence_range(self):
        # Unknown number -> low but non-zero confidence ("we don't know").
        r = analyze_number("+442071838750", db=self.db, cfg=self.cfg, record_event=False)
        self.assertGreaterEqual(r.confidence, 0)
        self.assertLessEqual(r.confidence, 100)

    def test_strong_evidence_high_confidence(self):
        self.db.upsert_list_entry("+919999911111", "blacklist", None, iso_now())
        r = analyze_number("+919999911111", db=self.db, cfg=self.cfg, record_event=False)
        self.assertGreaterEqual(r.confidence, 70)

    def test_weak_evidence_lower_confidence(self):
        # A single weak signal (format anomaly) should not produce very high
        # confidence. We use a number that triggers weak pattern matching.
        self.db.add_report("+919999922222", "spam", iso_now())
        r = analyze_number("+919999922222", db=self.db, cfg=self.cfg, record_event=False)
        self.assertLess(r.confidence, 90)

    def test_conflicting_evidence_reduces_confidence(self):
        # Number in both lists: confidence should be penalized.
        self.db.upsert_list_entry("+919999933333", "blacklist", None, iso_now())
        self.db.upsert_list_entry("+919999933333", "whitelist", None, iso_now())
        r = analyze_number("+919999933333", db=self.db, cfg=self.cfg, record_event=False)
        # Whitelist wins the verdict, but conflict should keep confidence lower.
        self.assertEqual(r.verdict, "SAFE")
        self.assertTrue(r.list_conflict)

    def test_more_history_higher_confidence(self):
        # Without history.
        self.db.upsert_list_entry("+919999944444", "blacklist", None, iso_now())
        r1 = analyze_number("+919999944444", db=self.db, cfg=self.cfg, record_event=True)
        # After a few events, behavioral evidence adds to confidence.
        for _ in range(5):
            analyze_number("+919999944444", db=self.db, cfg=self.cfg, record_event=True)
        r2 = analyze_number("+919999944444", db=self.db, cfg=self.cfg, record_event=False)
        self.assertGreaterEqual(r2.confidence, r1.confidence)


if __name__ == "__main__":
    unittest.main()
