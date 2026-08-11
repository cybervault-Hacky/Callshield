"""Phase 7 reputation CLI and masked listing tests."""

import unittest

from callshield.database import Database
from tests._common import IsolatedEnv, run_cli
from tests._reputation import add_event


class TestReputationCLI(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.number = "+919876543210"

    def tearDown(self):
        self.env.stop()

    def seed(self):
        db = Database(self.cfg.database_path)
        try:
            for _ in range(4):
                add_event(db, self.number, risk=75, confidence=80, verdict="HIGH_RISK", action="BLOCK")
        finally:
            db.close()

    def test_reputation_number_output_is_masked(self):
        self.seed()
        code, output = run_cli(self.cfg, "reputation", self.number)
        self.assertEqual(code, 0)
        self.assertNotIn(self.number, output)
        self.assertIn("Risk:", output)
        self.assertIn("Confidence:", output)
        self.assertIn("Trend:", output)
        self.assertIn("Reasons:", output)

    def test_reputation_without_number_lists_profiles(self):
        self.seed()
        run_cli(self.cfg, "reputation", self.number)
        code, output = run_cli(self.cfg, "reputation")
        self.assertEqual(code, 0)
        self.assertIn("CALLSHIELD REPUTATION", output)
        self.assertIn("543210"[-4:], output)
        self.assertNotIn(self.number, output)

    def test_reputation_list_alias(self):
        self.seed()
        run_cli(self.cfg, "reputation", self.number)
        code, output = run_cli(self.cfg, "reputation", "list")
        self.assertEqual(code, 0)
        self.assertIn("SCORE", output)

    def test_invalid_number_fails_safely(self):
        code, output = run_cli(self.cfg, "reputation", "invalid")
        self.assertNotEqual(code, 0)
        self.assertIn("Error", output)


if __name__ == "__main__":
    unittest.main()
