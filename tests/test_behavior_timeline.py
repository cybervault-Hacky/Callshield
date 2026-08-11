"""Phase 8 bounded measurable behavioral timeline tests."""

import unittest

from callshield.adaptive import BehaviorEngine, BehaviorStorage
from callshield.database import Database
from callshield.reputation import number_fingerprint
from tests._adaptive import observation
from tests._common import IsolatedEnv


class TestBehaviorTimeline(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(intelligence_query_limit=10)
        self.db = Database(self.cfg.database_path)
        self.storage = BehaviorStorage(self.db, self.cfg)
        self.number = "+919876543210"
        self.fingerprint = number_fingerprint(self.number)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def add(self, item):
        return BehaviorEngine(self.db, self.cfg).add_observation(self.number, item)

    def test_timeline_is_chronological_and_bounded(self):
        for index, risk in enumerate((20, 40, 70), 1):
            self.assertTrue(self.add(observation(index, risk)))
        timeline = self.storage.timeline(self.fingerprint)
        self.assertEqual([item.risk_score for item in timeline], [20, 40, 70])
        self.assertLessEqual(len(timeline), self.cfg.intelligence_query_limit)

    def test_duplicate_event_is_not_inserted_twice(self):
        item = observation(1, 50)
        self.assertTrue(self.add(item))
        self.assertFalse(self.add(item))
        self.assertEqual(len(self.storage.timeline(self.fingerprint)), 1)

    def test_outcome_and_confirmation_are_distinct(self):
        item = observation(2, 90, recommended="BLOCK", applied="UNKNOWN")
        self.add(item)
        self.assertTrue(
            self.storage.update_outcome(
                item.event_id,
                recommended_action="BLOCK",
                applied_action="BLOCK",
            )
        )
        self.assertTrue(self.storage.confirm(item.event_id))
        value = self.storage.timeline(self.fingerprint)[0]
        self.assertEqual(value.recommended_action, "BLOCK")
        self.assertEqual(value.applied_action, "BLOCK")
        self.assertTrue(value.confirmed)

    def test_timeline_contains_only_available_measurements(self):
        self.add(observation(3, 60, event_type="USER_REPORT"))
        value = self.storage.timeline(self.fingerprint)[0].to_dict()
        self.assertNotIn("duration", value)
        self.assertNotIn("answered", value)
        self.assertNotIn("location", value)
        self.assertNotIn("caller_identity", value)

    def test_storage_has_no_plaintext_number_column(self):
        columns = {
            row[1]
            for row in self.db._conn.execute(
                "PRAGMA table_info(intelligence_observations)"
            ).fetchall()
        }
        self.assertNotIn("number", columns)
        self.assertIn("number_hash", columns)
        self.assertIn("number_masked", columns)


if __name__ == "__main__":
    unittest.main()
