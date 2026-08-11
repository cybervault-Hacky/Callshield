"""Phase 6 SQLite integrity, schema, locking, and rollback tests."""

import sqlite3
import unittest
import uuid
from pathlib import Path

from callshield.database import Database, SCHEMA_VERSION
from callshield.utils import DatabaseError, iso_now
from tests._common import IsolatedEnv


class TestDatabaseIntegrity(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_wal_foreign_keys_integrity_and_schema(self):
        database = Database(self.cfg.database_path)
        try:
            self.assertEqual(database._conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(
                str(database._conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
                "wal",
            )
            self.assertTrue(database.integrity_check())
            self.assertTrue(database.validate_schema())
            version = database._conn.execute(
                "SELECT version FROM schema_version"
            ).fetchone()[0]
            self.assertEqual(version, SCHEMA_VERSION)
        finally:
            database.close()

    def test_phase6_indexes_exist(self):
        database = Database(self.cfg.database_path)
        try:
            indexes = {
                row[1]
                for row in database._conn.execute(
                    "PRAGMA index_list(screening_events)"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "idx_screening_timestamp",
                    "idx_screening_hash",
                    "idx_screening_event_id",
                    "idx_screening_applied",
                    "idx_screening_policy_action",
                }.issubset(indexes)
            )
        finally:
            database.close()

    def test_transaction_rolls_back_on_failure(self):
        database = Database(self.cfg.database_path)
        try:
            with self.assertRaises(RuntimeError):
                with database.transaction():
                    database._conn.execute(
                        "INSERT INTO settings(key,value) VALUES('rollback-test','x')"
                    )
                    raise RuntimeError("fail")
            self.assertIsNone(database.get_setting("rollback-test"))
        finally:
            database.close()

    def test_corruption_is_detected(self):
        path = Path(self.cfg.database_path)
        path.unlink(missing_ok=True)
        path.write_bytes(b"not a sqlite database")
        with self.assertRaises(DatabaseError):
            Database(path)

    def test_database_lock_is_bounded_and_screening_write_is_atomic(self):
        database = Database(self.cfg.database_path)
        database.close()
        lock = sqlite3.connect(self.cfg.database_path, timeout=1)
        lock.execute("BEGIN IMMEDIATE")
        lock.execute("UPDATE settings SET value=value")
        contender = None
        try:
            with self.assertRaises(DatabaseError):
                contender = Database(self.cfg.database_path, timeout=0.05)
                contender.add_screening_event(
                    timestamp=iso_now(),
                    number="+919876543210",
                    risk_score=95,
                    confidence=95,
                    verdict="MALICIOUS",
                    recommended_action="BLOCK",
                    applied_action="BLOCK",
                    mode="ACTIVE",
                    policy_action="BLOCK",
                    policy_name="BALANCED",
                    threshold=85,
                    confidence_threshold=80,
                    event_id=str(uuid.uuid4()),
                )
        finally:
            if contender is not None:
                contender.close()
            lock.rollback()
            lock.close()
        check = Database(self.cfg.database_path)
        try:
            self.assertEqual(check.count_screening_events(), 0)
            self.assertTrue(check.integrity_check())
        finally:
            check.close()

    def test_schema_validation_detects_missing_column(self):
        database = Database(self.cfg.database_path)
        try:
            database._conn.execute("ALTER TABLE screening_events RENAME TO old_screening")
            database._conn.execute(
                "CREATE TABLE screening_events(id INTEGER PRIMARY KEY)"
            )
            with self.assertRaises(DatabaseError):
                database.validate_schema()
        finally:
            database.close()


if __name__ == "__main__":
    unittest.main()
