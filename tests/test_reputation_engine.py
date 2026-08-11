"""Phase 7 reputation profile engine tests."""

import unittest
from unittest import mock

from callshield.database import Database
from callshield.reputation import ReputationEngine
from callshield.utils import iso_now
from tests._common import IsolatedEnv
from tests._reputation import add_event, analysis, measured_signal


class TestReputationEngine(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)
        self.engine = ReputationEngine(self.db, self.cfg)
        self.number = "+919876543210"

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_empty_history_is_unknown_allow(self):
        profile = self.engine.calculate(self.number, analysis=None)
        self.assertEqual(profile.risk, "UNKNOWN")
        self.assertEqual(profile.risk_score, 0)
        self.assertEqual(profile.confidence, 0)
        self.assertEqual(profile.recommendation, "ALLOW")
        self.assertEqual(profile.reasons, [])

    def test_one_event_is_not_definitive(self):
        add_event(self.db, self.number, risk=65, confidence=50, verdict="HIGH_RISK")
        profile = self.engine.calculate(self.number)
        self.assertEqual(profile.calls_seen, 1)
        self.assertLess(profile.confidence, 50)
        self.assertEqual(profile.trend, "UNKNOWN")

    def test_repeated_calls_create_measured_frequency_signal(self):
        for _ in range(7):
            add_event(self.db, self.number, risk=20, confidence=40)
        profile = self.engine.calculate(self.number)
        names = {signal.name for signal in profile.signals}
        self.assertIn("recent_call_frequency", names)
        self.assertTrue(any("7 calls observed within 24 hours" in reason for reason in profile.reasons))

    def test_reports_and_historical_blocks_are_measured(self):
        for _ in range(2):
            self.db.add_report(self.number, "local report", iso_now())
        for _ in range(3):
            add_event(
                self.db,
                self.number,
                risk=90,
                confidence=85,
                verdict="MALICIOUS",
                action="BLOCK",
            )
        profile = self.engine.calculate(self.number)
        names = {signal.name for signal in profile.signals}
        self.assertIn("user_reports", names)
        self.assertIn("historical_block_recommendations", names)
        self.assertEqual(profile.user_reports, 2)
        self.assertEqual(profile.block_recommendations, 3)

    def test_existing_detector_signals_are_reused(self):
        profile = self.engine.calculate(
            self.number,
            analysis=analysis(
                70,
                80,
                [measured_signal("manual_user_report", 25, 90, "Measured local report")],
            ),
        )
        self.assertIn("detector_manual_user_report", {s.name for s in profile.signals})
        self.assertIn("Measured local report", profile.reasons)

    def test_storage_failure_returns_unknown_allow(self):
        with mock.patch.object(
            self.engine.storage, "measurements", side_effect=RuntimeError("corrupt")
        ):
            profile = self.engine.calculate(self.number, analysis=analysis(100, 100))
        self.assertFalse(profile.available)
        self.assertEqual(profile.risk, "UNKNOWN")
        self.assertEqual(profile.recommendation, "ALLOW")


if __name__ == "__main__":
    unittest.main()
