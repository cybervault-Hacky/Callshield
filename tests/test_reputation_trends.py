"""Phase 7 trend detection tests using real observations."""

import unittest

from callshield.database import Database
from callshield.reputation import ReputationEngine
from callshield.reputation.history import detect_trend
from tests._common import IsolatedEnv
from tests._reputation import analysis, measured_signal


class TestReputationTrends(unittest.TestCase):
    def test_requires_three_observations(self):
        self.assertEqual(detect_trend([], 80), "UNKNOWN")
        self.assertEqual(detect_trend([20], 80), "UNKNOWN")

    def test_worsening_improving_and_stable(self):
        self.assertEqual(detect_trend([20, 45], 80), "WORSENING")
        self.assertEqual(detect_trend([90, 55], 20), "IMPROVING")
        self.assertEqual(detect_trend([40, 45], 42), "STABLE")

    def test_engine_reports_worsening_from_history(self):
        env = IsolatedEnv().start()
        try:
            cfg = env.make_config()
            db = Database(cfg.database_path)
            engine = ReputationEngine(db, cfg)
            number = "+919999933333"
            try:
                for score in (20, 50, 85):
                    profile = engine.calculate(
                        number,
                        analysis=analysis(
                            score,
                            80,
                            [measured_signal(reason=f"Measured {score}")],
                        ),
                    )
                self.assertEqual(profile.trend, "WORSENING")
                self.assertTrue(any("increased" in reason for reason in profile.reasons))
            finally:
                db.close()
        finally:
            env.stop()

    def test_engine_reports_improving_from_history(self):
        env = IsolatedEnv().start()
        try:
            cfg = env.make_config()
            db = Database(cfg.database_path)
            engine = ReputationEngine(db, cfg)
            number = "+919999944444"
            try:
                for score in (90, 50, 10):
                    profile = engine.calculate(
                        number,
                        analysis=analysis(
                            score,
                            80,
                            [measured_signal(reason=f"Measured {score}")],
                        ),
                    )
                self.assertEqual(profile.trend, "IMPROVING")
            finally:
                db.close()
        finally:
            env.stop()


if __name__ == "__main__":
    unittest.main()
