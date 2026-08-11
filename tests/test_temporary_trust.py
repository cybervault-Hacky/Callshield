"""Phase 7 bounded temporary trust tests."""

import unittest
from datetime import datetime, timedelta, timezone

from callshield.database import Database
from callshield.reputation import ReputationStorage, number_fingerprint, trust_expiry
from tests._common import IsolatedEnv, run_cli


class TestTemporaryTrust(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.number = "+919876543210"

    def tearDown(self):
        self.env.stop()

    def test_cli_temporary_trust(self):
        code, output = run_cli(self.cfg, "trust", self.number, "--for", "24h")
        self.assertEqual(code, 0)
        self.assertIn("Expires:", output)
        self.assertNotIn("Expires:             never", output)

    def test_expired_trust_disappears_automatically(self):
        db = Database(self.cfg.database_path)
        try:
            storage = ReputationStorage(db, self.cfg)
            fingerprint = number_fingerprint(self.number)
            past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(
                timespec="seconds"
            )
            storage.set_trust(fingerprint, "+919*****3210", expires_at=past)
            self.assertIsNone(storage.get_trust(fingerprint))
            count = db._conn.execute("SELECT COUNT(*) FROM trusted_numbers").fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            db.close()

    def test_duration_is_bounded(self):
        with self.assertRaises(ValueError):
            trust_expiry("366d", self.cfg.trust_max_seconds)
        with self.assertRaises(ValueError):
            trust_expiry("forever", self.cfg.trust_max_seconds)
        expiry = trust_expiry("30m", self.cfg.trust_max_seconds)
        self.assertTrue(expiry.endswith("+00:00"))

    def test_invalid_duration_fails_without_record(self):
        code, output = run_cli(self.cfg, "trust", self.number, "--for", "9999d")
        self.assertNotEqual(code, 0)
        self.assertIn("Error", output)
        db = Database(self.cfg.database_path)
        try:
            self.assertEqual(
                db._conn.execute("SELECT COUNT(*) FROM trusted_numbers").fetchone()[0],
                0,
            )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
