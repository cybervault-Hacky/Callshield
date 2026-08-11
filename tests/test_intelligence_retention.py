"""Phase 8 deterministic derived-data retention tests."""

import unittest
from datetime import datetime, timedelta, timezone

from callshield.adaptive import BehaviorEngine, BehaviorStorage, IntelligenceSnapshot
from callshield.database import Database
from callshield.reputation import number_fingerprint
from tests._adaptive import observation
from tests._common import IsolatedEnv
from tests._reputation import add_event


class TestIntelligenceRetention(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(
            intelligence_observation_limit=20,
            intelligence_profile_limit=100,
            intelligence_history_days=7,
        )
        self.db = Database(self.cfg.database_path)
        self.storage = BehaviorStorage(self.db, self.cfg)
        self.number = "+919876543210"

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_observation_limit(self):
        engine = BehaviorEngine(self.db, self.cfg)
        for index in range(30):
            engine.add_observation(self.number, observation(index + 1, index))
        count = self.db._conn.execute(
            "SELECT COUNT(*) FROM intelligence_observations WHERE number_hash=?",
            (number_fingerprint(self.number),),
        ).fetchone()[0]
        self.assertEqual(count, 20)

    def test_age_cleanup(self):
        old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat(
            timespec="seconds"
        )
        recent = datetime.now(timezone.utc).isoformat(timespec="seconds")
        engine = BehaviorEngine(self.db, self.cfg)
        engine.add_observation(
            self.number, observation(1, 20, timestamp=old)
        )
        engine.add_observation(
            self.number, observation(2, 30, timestamp=recent)
        )
        timeline = self.storage.timeline(number_fingerprint(self.number))
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0].risk_score, 30)

    def test_profile_limit_removes_oldest_deterministically(self):
        for index in range(105):
            snapshot = IntelligenceSnapshot(
                number_hash=f"{index:064x}",
                number_masked=f"***{index:04d}",
                baseline_score=10,
                current_score=10,
                reputation_score=10,
                reputation_confidence=10,
            )
            self.storage.save_snapshot(snapshot)
        rows = self.db._conn.execute(
            "SELECT number_hash FROM intelligence_profiles ORDER BY updated_at, number_hash"
        ).fetchall()
        self.assertEqual(len(rows), 100)
        hashes = {row[0] for row in rows}
        self.assertNotIn(f"{0:064x}", hashes)
        self.assertIn(f"{104:064x}", hashes)

    def test_cleanup_never_deletes_core_events(self):
        for _ in range(5):
            add_event(self.db, self.number, risk=50, confidence=50)
        engine = BehaviorEngine(self.db, self.cfg)
        for index in range(30):
            engine.add_observation(self.number, observation(index + 1, index))
        self.storage.cleanup(number_fingerprint(self.number))
        self.assertEqual(self.db.count_events_for_number(self.number), 5)


if __name__ == "__main__":
    unittest.main()
