"""Phase 7 separate evidence-confidence tests."""

import unittest

from callshield.database import Database
from callshield.reputation import ReputationEngine
from tests._common import IsolatedEnv
from tests._reputation import add_event, analysis, measured_signal


class TestReputationConfidence(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)
        self.engine = ReputationEngine(self.db, self.cfg)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_high_risk_can_have_low_confidence(self):
        profile = self.engine.calculate(
            "+919999955551",
            analysis=analysis(
                90, 20, [measured_signal(score=20, confidence=20, reason="single signal")]
            ),
        )
        self.assertGreaterEqual(profile.risk_score, 80)
        self.assertLess(profile.confidence, 30)

    def test_more_observations_raise_confidence(self):
        number = "+919999955552"
        first = self.engine.calculate(number, analysis=analysis(60, 60), persist=False)
        for _ in range(10):
            add_event(self.db, number, risk=60, confidence=60, verdict="HIGH_RISK")
        later = self.engine.calculate(number, analysis=analysis(60, 60), persist=False)
        self.assertGreater(later.confidence, first.confidence)

    def test_confidence_remains_bounded(self):
        number = "+919999955553"
        for _ in range(50):
            add_event(self.db, number, risk=100, confidence=100, verdict="MALICIOUS", action="BLOCK")
        profile = self.engine.calculate(number, analysis=analysis(100, 100))
        self.assertLessEqual(profile.confidence, 100)
        self.assertGreaterEqual(profile.confidence, 0)


if __name__ == "__main__":
    unittest.main()
