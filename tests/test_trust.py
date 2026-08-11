"""Phase 7 explicit local trust tests."""

import unittest

from callshield.database import Database
from callshield.reputation import ReputationEngine, ReputationStorage, number_fingerprint
from tests._common import IsolatedEnv, run_cli
from tests._reputation import analysis


class TestTrust(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.number = "+919876543210"

    def tearDown(self):
        self.env.stop()

    def test_trust_and_untrust_cli_are_masked_and_reversible(self):
        code, output = run_cli(self.cfg, "trust", self.number)
        self.assertEqual(code, 0)
        self.assertNotIn(self.number, output)
        self.assertIn("Trusted:             YES", output)
        code, output = run_cli(self.cfg, "untrust", self.number)
        self.assertEqual(code, 0)
        self.assertIn("REMOVED", output)
        self.assertNotIn(self.number, output)

    def test_trust_is_idempotent(self):
        run_cli(self.cfg, "trust", self.number)
        run_cli(self.cfg, "trust", self.number)
        db = Database(self.cfg.database_path)
        try:
            count = db._conn.execute("SELECT COUNT(*) FROM trusted_numbers").fetchone()[0]
            self.assertEqual(count, 1)
        finally:
            db.close()

    def test_trusted_profile_never_recommends_block(self):
        run_cli(self.cfg, "trust", self.number)
        db = Database(self.cfg.database_path)
        try:
            profile = ReputationEngine(db, self.cfg).calculate(
                self.number, analysis=analysis(100, 100)
            )
            self.assertTrue(profile.trusted)
            self.assertEqual(profile.risk, "TRUSTED")
            self.assertEqual(profile.recommendation, "ALLOW")
        finally:
            db.close()

    def test_trust_table_contains_no_plaintext(self):
        run_cli(self.cfg, "trust", self.number)
        db = Database(self.cfg.database_path)
        try:
            row = db._conn.execute("SELECT * FROM trusted_numbers").fetchone()
            self.assertNotIn(self.number, str(tuple(row)))
            columns = {item[0] for item in db._conn.execute("SELECT * FROM trusted_numbers").description}
            self.assertNotIn("number", columns)
            self.assertIn("number_hash", columns)
        finally:
            db.close()

    def test_remove_missing_trust_is_safe(self):
        code, output = run_cli(self.cfg, "untrust", self.number)
        self.assertEqual(code, 0)
        self.assertIn("NOT PRESENT", output)


if __name__ == "__main__":
    unittest.main()
