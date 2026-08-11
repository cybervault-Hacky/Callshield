"""Phase 8 intelligence CLI, JSON, history, and explain tests."""

import json
import unittest

from tests._common import IsolatedEnv, run_cli


class TestIntelligenceCLI(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.number = "+919876543210"

    def tearDown(self):
        self.env.stop()

    def seed(self):
        for _ in range(4):
            code, _ = run_cli(self.cfg, "scan", self.number, "--quiet")
            self.assertEqual(code, 0)

    def test_empty_intelligence_list(self):
        code, output = run_cli(self.cfg, "intelligence")
        self.assertEqual(code, 0)
        self.assertIn("No intelligence snapshots", output)

    def test_human_output_is_masked_and_distinguishes_actions(self):
        self.seed()
        code, output = run_cli(self.cfg, "intelligence", self.number)
        self.assertEqual(code, 0)
        self.assertNotIn(self.number, output)
        for label in (
            "Behavioral Trend:",
            "Risk Delta:",
            "OBSERVED:",
            "RECOMMENDED:",
            "APPLIED:",
            "CONFIRMED:",
            "Patterns:",
        ):
            self.assertIn(label, output)

    def test_json_output_is_private_and_serializable(self):
        self.seed()
        code, output = run_cli(self.cfg, "intelligence", self.number, "--json")
        self.assertEqual(code, 0)
        value = json.loads(output)
        self.assertNotIn("number_hash", value)
        self.assertNotIn(self.number, output)
        self.assertIn("behavioral_trend", value)
        self.assertIn("patterns", value)
        self.assertIn("risk_delta", value)
        self.assertIn("decision", value)

    def test_history_flag_shows_bounded_timeline(self):
        self.seed()
        code, output = run_cli(
            self.cfg, "intelligence", self.number, "--history"
        )
        self.assertEqual(code, 0)
        self.assertIn("Timeline:", output)
        self.assertIn("NUMBER_SCAN", output)

    def test_explain_flag_shows_measured_evidence(self):
        self.seed()
        code, output = run_cli(
            self.cfg, "intelligence", self.number, "--explain"
        )
        self.assertEqual(code, 0)
        self.assertIn("Evidence:", output)
        self.assertNotIn("short call", output.lower())

    def test_list_alias_shows_masked_snapshot(self):
        self.seed()
        run_cli(self.cfg, "intelligence", self.number)
        code, output = run_cli(self.cfg, "intelligence", "list")
        self.assertEqual(code, 0)
        self.assertIn("SCORE", output)
        self.assertNotIn(self.number, output)

    def test_invalid_number_fails_safely(self):
        code, output = run_cli(self.cfg, "intelligence", "invalid")
        self.assertNotEqual(code, 0)
        self.assertIn("Error", output)


if __name__ == "__main__":
    unittest.main()
