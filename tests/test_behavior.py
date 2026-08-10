import unittest

from callshield.database import Database
from callshield.detector import analyze_number
from callshield.intelligence.behavior import analyze_behavior
from callshield.utils import iso_now
from tests._common import IsolatedEnv


class TestBehavior(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_no_history(self):
        b = analyze_behavior(self.db, "+919999911111")
        self.assertEqual(b.total_events, 0)
        self.assertEqual(b.suspicious_events, 0)
        self.assertEqual(b.blocked_events, 0)
        self.assertEqual(b.user_reports, 0)
        self.assertEqual(b.activity_level, "NONE")

    def test_one_event(self):
        self.db.add_event(
            iso_now(),
            "+919999911111",
            risk_score=5,
            verdict="UNKNOWN",
            action="ALLOW",
            reason="no indicators",
        )
        b = analyze_behavior(self.db, "+919999911111")
        self.assertEqual(b.total_events, 1)
        self.assertEqual(b.allowed_events, 1)

    def test_repeated_blocks(self):
        for _ in range(3):
            self.db.add_event(
                iso_now(),
                "+919999922222",
                risk_score=90,
                verdict="HIGH_RISK",
                action="BLOCK",
                reason="blacklist",
            )
        b = analyze_behavior(self.db, "+919999922222")
        self.assertEqual(b.blocked_events, 3)
        self.assertEqual(b.suspicious_events, 3)
        self.assertIn(b.activity_level, ("MODERATE", "HIGH"))

    def test_reports_increment_count(self):
        self.db.add_report("+919999933333", "spam", iso_now())
        self.db.add_report("+919999933333", "scam", iso_now())
        b = analyze_behavior(self.db, "+919999933333")
        self.assertEqual(b.user_reports, 2)


if __name__ == "__main__":
    unittest.main()
