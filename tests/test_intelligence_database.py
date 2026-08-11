"""Phase 8 intelligence schema, migration, and privacy tests."""

import sqlite3
import unittest
from pathlib import Path

from callshield.database import Database, SCHEMA_VERSION
from tests._common import IsolatedEnv


class TestIntelligenceDatabase(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_schema_version_tables_and_indexes(self):
        db = Database(self.cfg.database_path)
        try:
            self.assertEqual(SCHEMA_VERSION, 7)
            self.assertTrue(db.validate_schema())
            tables = {
                row[0]
                for row in db._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertTrue(
                {"intelligence_observations", "intelligence_profiles"}.issubset(tables)
            )
            indexes = {
                row[0]
                for row in db._conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "idx_intelligence_observation_hash_time",
                    "idx_intelligence_observation_event",
                    "idx_intelligence_observation_type",
                    "idx_intelligence_profile_updated",
                }.issubset(indexes)
            )
        finally:
            db.close()

    def test_v6_to_v7_migration_preserves_existing_records(self):
        path = Path(self.cfg.database_path)
        db = Database(path)
        try:
            db.set_setting("phase7-preserve", "yes")
        finally:
            db.close()
        connection = sqlite3.connect(str(path))
        connection.execute("UPDATE schema_version SET version=6")
        connection.execute("DROP TABLE intelligence_observations")
        connection.execute("DROP TABLE intelligence_profiles")
        connection.commit()
        connection.close()
        migrated = Database(path)
        try:
            self.assertEqual(
                migrated._conn.execute("SELECT version FROM schema_version").fetchone()[0],
                7,
            )
            self.assertEqual(migrated.get_setting("phase7-preserve"), "yes")
            self.assertTrue(migrated.integrity_check())
        finally:
            migrated.close()

    def test_intelligence_tables_have_no_plaintext_number_column(self):
        db = Database(self.cfg.database_path)
        try:
            for table in ("intelligence_observations", "intelligence_profiles"):
                columns = {
                    row[1]
                    for row in db._conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()
                }
                self.assertNotIn("number", columns)
                self.assertIn("number_hash", columns)
                self.assertIn("number_masked", columns)
        finally:
            db.close()

    def test_fresh_database_integrity(self):
        db = Database(self.cfg.database_path)
        try:
            self.assertTrue(db.integrity_check())
            self.assertTrue(db.validate_schema())
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
