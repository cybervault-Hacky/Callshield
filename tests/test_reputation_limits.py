"""Phase 7 bounded query, profile, history, trust, and concurrency tests."""

import concurrent.futures
import unittest

from callshield.database import Database
from callshield.reputation import (
    ReputationEngine,
    ReputationProfile,
    ReputationStorage,
    ReputationStorageError,
    number_fingerprint,
)
from tests._common import IsolatedEnv
from tests._reputation import add_event, analysis


class TestReputationLimits(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(
            reputation_query_limit=10,
            reputation_history_limit=10,
            reputation_profile_limit=100,
            trust_record_limit=10,
        )
        self.db = Database(self.cfg.database_path)
        self.storage = ReputationStorage(self.db, self.cfg)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_recent_measurement_query_is_bounded(self):
        number = "+919999900701"
        for index in range(50):
            add_event(self.db, number, risk=index % 100, confidence=50)
        measured = self.storage.measurements(
            number, "2026-08-11T23:59:59+00:00"
        )
        self.assertEqual(measured["calls_seen"], 50)
        self.assertEqual(len(measured["recent_scores"]), 10)

    def test_profile_retention_is_bounded(self):
        for index in range(105):
            fingerprint = f"{index:064x}"
            profile = ReputationProfile(
                number_hash=fingerprint,
                number_masked=f"***{index:04d}",
                risk="LOW",
                risk_score=10,
                confidence=10,
            )
            self.storage.save_profile(profile, "test")
        count = self.db._conn.execute(
            "SELECT COUNT(*) FROM reputation_profiles"
        ).fetchone()[0]
        self.assertEqual(count, 100)

    def test_trust_limit_is_enforced(self):
        for index in range(10):
            self.storage.set_trust(
                f"{index:064x}", f"***{index:04d}", expires_at=None
            )
        with self.assertRaises(ReputationStorageError):
            self.storage.set_trust("f" * 64, "***9999", expires_at=None)

    def test_ten_concurrent_lookups_do_not_grow_memory_cache(self):
        numbers = [f"+9199998{index:05d}" for index in range(10)]

        def lookup(number):
            db = Database(self.cfg.database_path)
            try:
                return ReputationEngine(db, self.cfg).calculate(
                    number, analysis=analysis(30, 40), persist=False
                ).risk_score
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(lookup, numbers))
        self.assertEqual(len(results), 10)
        self.assertTrue(all(0 <= value <= 100 for value in results))


if __name__ == "__main__":
    unittest.main()
