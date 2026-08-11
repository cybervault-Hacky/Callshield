"""Phase 7 machine-readable reputation privacy tests."""

import json
import unittest

from callshield.database import Database
from tests._common import IsolatedEnv, run_cli
from tests._reputation import add_event


class TestReputationJSON(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.number = "+919876543210"

    def tearDown(self):
        self.env.stop()

    def test_json_schema_is_structured_and_private(self):
        db = Database(self.cfg.database_path)
        try:
            add_event(db, self.number, risk=80, confidence=70, verdict="HIGH_RISK")
        finally:
            db.close()
        code, output = run_cli(self.cfg, "reputation", self.number, "--json")
        self.assertEqual(code, 0)
        value = json.loads(output)
        for key in (
            "number_masked",
            "risk",
            "score",
            "confidence",
            "trend",
            "signals",
            "reasons",
            "history",
        ):
            self.assertIn(key, value)
        self.assertNotIn("number", value)
        self.assertNotIn("number_hash", value)
        self.assertNotIn(self.number, output)

    def test_list_json_contains_masked_profiles_only(self):
        run_cli(self.cfg, "reputation", self.number, "--json")
        code, output = run_cli(self.cfg, "reputation", "list", "--json")
        self.assertEqual(code, 0)
        value = json.loads(output)
        self.assertEqual(value["count"], 1)
        self.assertIn("number_masked", value["profiles"][0])
        self.assertNotIn(self.number, output)


if __name__ == "__main__":
    unittest.main()
