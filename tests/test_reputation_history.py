"""Phase 7 bounded reputation history tests."""

import unittest

from callshield.database import Database
from callshield.reputation import ReputationEngine, number_fingerprint
from tests._common import IsolatedEnv
from tests._reputation import analysis, measured_signal


class TestReputationHistory(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(reputation_history_limit=10)
        self.db = Database(self.cfg.database_path)
        self.engine = ReputationEngine(self.db, self.cfg)
        self.number = "+919999922222"

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def observe(self, score):
        return self.engine.calculate(
            self.number,
            analysis=analysis(
                score,
                80,
                [measured_signal("observation", 1, 80, f"Measured score {score}")],
            ),
        )

    def test_meaningful_changes_are_recorded(self):
        self.observe(20)
        self.observe(55)
        result = self.observe(90)
        self.assertGreaterEqual(len(result.history), 3)
        newest = result.history[0]
        self.assertEqual(newest.old_score, 55)
        self.assertEqual(newest.new_score, 90)
        self.assertEqual(newest.risk_before, "MODERATE")
        self.assertEqual(newest.risk_after, "CRITICAL")
        self.assertIn("observation", newest.trigger)

    def test_small_unchanged_observation_is_not_unbounded(self):
        self.observe(20)
        self.observe(22)
        history = self.engine.storage.history(number_fingerprint(self.number))
        self.assertEqual(len(history), 1)

    def test_history_retention_limit(self):
        for index in range(25):
            self.observe(10 if index % 2 else 90)
        history = self.engine.storage.history(number_fingerprint(self.number), limit=100)
        self.assertEqual(len(history), 10)

    def test_history_contains_no_plaintext_number(self):
        self.observe(70)
        rows = self.db._conn.execute("SELECT * FROM reputation_history").fetchall()
        self.assertTrue(rows)
        columns = {description[0] for description in self.db._conn.execute("SELECT * FROM reputation_history LIMIT 1").description}
        self.assertNotIn("number", columns)
        self.assertNotIn(self.number, str([tuple(row) for row in rows]))


if __name__ == "__main__":
    unittest.main()
