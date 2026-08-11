"""Phase 8 concurrent lookup, insertion, and trust mutation tests."""

import concurrent.futures
import unittest
import uuid

from callshield.adaptive import BehaviorEngine
from callshield.database import Database
from callshield.reputation import ReputationEngine, ReputationStorage, number_fingerprint
from callshield.utils import iso_now, mask_number
from tests._adaptive import observation
from tests._common import IsolatedEnv
from tests._reputation import analysis


class TestIntelligenceConcurrency(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.number = "+919876543210"
        db = Database(self.cfg.database_path)
        try:
            for index in range(10):
                BehaviorEngine(db, self.cfg).add_observation(
                    self.number, observation(index + 1, 20 + index * 3)
                )
        finally:
            db.close()

    def tearDown(self):
        self.env.stop()

    def lookup(self, _index):
        db = Database(self.cfg.database_path)
        try:
            reputation = ReputationEngine(db, self.cfg).calculate(
                self.number, analysis=analysis(50, 60), persist=False
            )
            return BehaviorEngine(db, self.cfg).snapshot(
                self.number,
                reputation=reputation,
                detection={"recommended_action": "ALLOW"},
                persist=False,
            )
        finally:
            db.close()

    def test_five_concurrent_lookups(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            values = list(executor.map(self.lookup, range(5)))
        self.assertEqual(len(values), 5)
        self.assertTrue(all(value.available for value in values))
        self.assertEqual(len({value.current_score for value in values}), 1)

    def test_ten_concurrent_lookups(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            values = list(executor.map(self.lookup, range(10)))
        self.assertEqual(len(values), 10)
        self.assertTrue(all(value.available for value in values))

    def test_concurrent_event_insertion_and_lookup(self):
        def insert(index):
            db = Database(self.cfg.database_path)
            try:
                return BehaviorEngine(db, self.cfg).add_observation(
                    self.number, observation(100 + index, 60 + index)
                )
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(insert, index) for index in range(5)]
            futures += [executor.submit(self.lookup, index) for index in range(5)]
            values = [future.result(timeout=10) for future in futures]
        self.assertTrue(all(values[:5]))
        snapshots = values[5:]
        self.assertTrue(all(value.available for value in snapshots))
        db = Database(self.cfg.database_path)
        try:
            self.assertTrue(BehaviorEngine(db, self.cfg).storage.integrity_check())
        finally:
            db.close()

    def test_concurrent_trust_changes_and_lookup(self):
        fingerprint = number_fingerprint(self.number)

        def change(index):
            db = Database(self.cfg.database_path)
            try:
                storage = ReputationStorage(db, self.cfg)
                if index % 2:
                    storage.remove_trust(fingerprint)
                else:
                    storage.set_trust(
                        fingerprint,
                        mask_number(self.number),
                        expires_at=None,
                    )
                return True
            finally:
                db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(change, index) for index in range(5)]
            futures += [executor.submit(self.lookup, index) for index in range(5)]
            values = [future.result(timeout=10) for future in futures]
        self.assertTrue(all(values[:5]))
        self.assertTrue(all(value.available for value in values[5:]))


if __name__ == "__main__":
    unittest.main()
