"""Phase 8 adaptive intelligence failure → ALLOW tests."""

import unittest
from unittest import mock

from callshield.adaptive import IntelligenceSnapshot
from callshield.events import Event
from callshield.events.processor import EventProcessor
from tests._common import IsolatedEnv, run_cli


class TestIntelligenceFailOpen(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(
            screening_enabled=True,
            screening_mode="ACTIVE",
            active_mode_confirmed=True,
        )

    def tearDown(self):
        self.env.stop()

    def test_behavior_engine_failure_in_screening_applies_allow(self):
        unavailable = IntelligenceSnapshot.unavailable("hash", "+***", "corrupt")
        with mock.patch(
            "callshield.events.processor.BehaviorEngine.snapshot",
            return_value=unavailable,
        ):
            result = EventProcessor(self.cfg).process(
                Event(
                    event_type="INCOMING_CALL",
                    number="+919999900801",
                    source="android_call_screening",
                )
            )
        self.assertEqual(result["policy"]["applied_action"], "ALLOW")
        self.assertEqual(result["policy"]["reason"], "INTELLIGENCE_UNAVAILABLE")

    def test_unexpected_behavior_exception_isolated(self):
        with mock.patch(
            "callshield.events.processor.BehaviorEngine.snapshot",
            side_effect=RuntimeError("unexpected"),
        ):
            result = EventProcessor(self.cfg).process(
                Event(
                    event_type="INCOMING_CALL",
                    number="+919999900802",
                    source="android_call_screening",
                )
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["detection"]["applied_action"], "ALLOW")

    def test_database_unavailable_cli_returns_allow(self):
        self.cfg.database_path = "/nonexistent/callshield/intelligence.db"
        code, output = run_cli(
            self.cfg, "intelligence", "+919876543210"
        )
        self.assertEqual(code, 0)
        self.assertIn("Recommended:         ALLOW", output)
        self.assertIn("fail-open", output)

    def test_invalid_number_fails_safely(self):
        code, output = run_cli(self.cfg, "intelligence", "invalid")
        self.assertNotEqual(code, 0)
        self.assertIn("Error", output)


if __name__ == "__main__":
    unittest.main()
