"""Phase 7 explanation provenance tests."""

import unittest

from callshield.database import Database
from callshield.reputation import ReputationEngine
from callshield.utils import iso_now
from tests._common import IsolatedEnv
from tests._reputation import add_event, analysis


class TestReputationExplanations(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)
        self.engine = ReputationEngine(self.db, self.cfg)
        self.number = "+919999966661"

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_every_reason_has_a_measured_signal(self):
        for _ in range(4):
            add_event(self.db, self.number, risk=80, confidence=80, verdict="HIGH_RISK", action="BLOCK")
        self.db.add_report(self.number, "report", iso_now())
        profile = self.engine.calculate(self.number, analysis=analysis(80, 80))
        signal_reasons = {signal.reason for signal in profile.signals}
        for reason in profile.reasons:
            if "reputation risk" not in reason:
                self.assertIn(reason, signal_reasons)

    def test_no_frequency_reason_below_measured_threshold(self):
        for _ in range(2):
            add_event(self.db, self.number, risk=20, confidence=30)
        profile = self.engine.calculate(self.number)
        self.assertFalse(any("within 24 hours" in reason for reason in profile.reasons))

    def test_no_short_call_claim_without_duration_data(self):
        for _ in range(8):
            add_event(self.db, self.number, risk=30, confidence=40)
        profile = self.engine.calculate(self.number)
        self.assertFalse(any("short call" in reason.lower() for reason in profile.reasons))

    def test_empty_profile_does_not_invent_reasons(self):
        profile = self.engine.calculate(self.number)
        self.assertEqual(profile.reasons, [])


if __name__ == "__main__":
    unittest.main()
