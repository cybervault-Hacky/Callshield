"""Phase 7 deterministic bounded reputation scoring tests."""

import unittest

from callshield.database import Database
from callshield.reputation import ReputationEngine, ReputationStorage, number_fingerprint
from tests._common import IsolatedEnv
from tests._reputation import add_event, analysis, measured_signal


class TestReputationScoring(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)
        self.engine = ReputationEngine(self.db, self.cfg)
        self.number = "+919999911111"

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_deterministic_result(self):
        for _ in range(3):
            add_event(self.db, self.number, risk=50, confidence=60, verdict="SUSPICIOUS")
        value = analysis(55, 65, [measured_signal(reason="measured anomaly")])
        first = self.engine.calculate(self.number, analysis=value, persist=False)
        second = self.engine.calculate(self.number, analysis=value, persist=False)
        self.assertEqual(first.risk_score, second.risk_score)
        self.assertEqual(first.confidence, second.confidence)
        self.assertEqual(first.reasons, second.reasons)

    def test_score_is_bounded(self):
        for _ in range(20):
            self.db.add_report(self.number, "report", "2026-08-11T00:00:00+00:00")
            add_event(self.db, self.number, risk=100, confidence=100, verdict="MALICIOUS", action="BLOCK")
        profile = self.engine.calculate(self.number, analysis=analysis(100, 100))
        self.assertEqual(profile.risk_score, 100)
        self.assertLessEqual(profile.confidence, 100)

    def test_historical_allows_can_reduce_score(self):
        for _ in range(5):
            add_event(self.db, self.number, risk=20, confidence=40, action="ALLOW")
        profile = self.engine.calculate(self.number, analysis=analysis(20, 40))
        self.assertIn("historical_allows", {signal.name for signal in profile.signals})
        self.assertLess(profile.risk_score, 20)

    def test_explicit_trust_sets_trusted_zero(self):
        storage = ReputationStorage(self.db, self.cfg)
        storage.set_trust(
            number_fingerprint(self.number),
            "+919*****1111",
            expires_at=None,
        )
        profile = self.engine.calculate(self.number, analysis=analysis(100, 100))
        self.assertTrue(profile.trusted)
        self.assertEqual(profile.risk, "TRUSTED")
        self.assertEqual(profile.risk_score, 0)
        self.assertEqual(profile.recommendation, "ALLOW")


if __name__ == "__main__":
    unittest.main()
