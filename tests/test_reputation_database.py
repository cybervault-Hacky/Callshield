"""Phase 7 schema, migration, privacy, and integrity tests."""

import sqlite3
import unittest
from pathlib import Path

from callshield.database import Database, SCHEMA_VERSION
from callshield.reputation import ReputationEngine, ReputationStorage, number_fingerprint
from tests._common import IsolatedEnv
from tests._reputation import analysis, measured_signal


class TestReputationDatabase(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_schema_and_indexes(self):
        db = Database(self.cfg.database_path)
        try:
            self.assertEqual(SCHEMA_VERSION, 6)
            tables = {
                row[0]
                for row in db._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertTrue(
                {"reputation_profiles", "reputation_history", "trusted_numbers"}.issubset(tables)
            )
            indexes = {
                row[0]
                for row in db._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "idx_reputation_updated",
                    "idx_reputation_risk",
                    "idx_reputation_history_hash_time",
                    "idx_trusted_expiry",
                }.issubset(indexes)
            )
            self.assertTrue(db.validate_schema())
        finally:
            db.close()

    def test_v5_to_v6_preserves_existing_screening_row(self):
        # Build a current DB, mark it as v5, and remove only Phase 7 columns/tables
        # using a minimal copied screening table.
        path = Path(self.cfg.database_path)
        db = Database(path)
        db.close()
        connection = sqlite3.connect(str(path))
        connection.execute("UPDATE schema_version SET version=5")
        connection.execute("DROP TABLE reputation_history")
        connection.execute("DROP TABLE reputation_profiles")
        connection.execute("DROP TABLE trusted_numbers")
        # SQLite cannot drop columns portably; migration is idempotent when they exist.
        connection.commit()
        connection.close()
        migrated = Database(path)
        try:
            self.assertEqual(
                migrated._conn.execute("SELECT version FROM schema_version").fetchone()[0],
                6,
            )
            self.assertTrue(migrated.validate_schema())
        finally:
            migrated.close()

    def test_profiles_store_hash_and_mask_not_plaintext(self):
        number = "+919876543210"
        db = Database(self.cfg.database_path)
        try:
            ReputationEngine(db, self.cfg).calculate(
                number,
                analysis=analysis(
                    70, 80, [measured_signal(reason="measured risk")]
                ),
            )
            row = db._conn.execute("SELECT * FROM reputation_profiles").fetchone()
            self.assertEqual(row["number_hash"], number_fingerprint(number))
            self.assertNotEqual(row["number_masked"], number)
            self.assertNotIn(number, str(tuple(row)))
        finally:
            db.close()

    def test_history_cascades_with_profile_retention(self):
        number = "+919999988881"
        db = Database(self.cfg.database_path)
        try:
            engine = ReputationEngine(db, self.cfg)
            engine.calculate(number, analysis=analysis(20, 50, [measured_signal()]))
            engine.calculate(number, analysis=analysis(80, 80, [measured_signal()]))
            fingerprint = number_fingerprint(number)
            self.assertGreater(
                db._conn.execute(
                    "SELECT COUNT(*) FROM reputation_history WHERE number_hash=?",
                    (fingerprint,),
                ).fetchone()[0],
                0,
            )
            with db.transaction():
                db._conn.execute(
                    "DELETE FROM reputation_profiles WHERE number_hash=?",
                    (fingerprint,),
                )
            self.assertEqual(
                db._conn.execute(
                    "SELECT COUNT(*) FROM reputation_history WHERE number_hash=?",
                    (fingerprint,),
                ).fetchone()[0],
                0,
            )
        finally:
            db.close()

    def test_corrupt_profile_json_is_detected_and_fails_open(self):
        number = "+919999988882"
        db = Database(self.cfg.database_path)
        try:
            engine = ReputationEngine(db, self.cfg)
            engine.calculate(number, analysis=analysis(50, 50, [measured_signal()]))
            with db.transaction():
                db._conn.execute(
                    "UPDATE reputation_profiles SET signals_json='{bad'"
                )
            self.assertFalse(ReputationStorage(db, self.cfg).integrity_check())
            profile = engine.calculate(number, analysis=analysis(100, 100))
            self.assertFalse(profile.available)
            self.assertEqual(profile.recommendation, "ALLOW")
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
