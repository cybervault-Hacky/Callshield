"""Tests for Phase 4 screening (INCOMING_CALL, dry-run, timeout, fallback)."""

import time
import unittest

from callshield.events import Event
from callshield.events.processor import EventProcessor
from tests._common import IsolatedEnv
from callshield.database import Database


class TestScreeningProcessor(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_incoming_call_safe(self):
        proc = EventProcessor(self.cfg)
        ev = Event(event_type="INCOMING_CALL", number="+442071838750", source="android_call_screening")
        result = proc.process(ev)
        self.assertEqual(result["status"], "processed")
        det = result["detection"]
        self.assertEqual(det["recommended_action"], "ALLOW")
        self.assertEqual(det["applied_action"], "ALLOW")
        self.assertEqual(det["mode"], "DRY_RUN")
        # Check screening event persisted
        self.assertEqual(self.db.count_screening_events(), 1)

    def test_incoming_call_high_risk_dry_run(self):
        # High risk via blacklist should recommend BLOCK but applied ALLOW in dry-run
        self.db.upsert_list_entry("+919999900099", "blacklist", None, "2026-08-10T00:00:00Z")
        proc = EventProcessor(self.cfg)
        ev = Event(event_type="INCOMING_CALL", number="+919999900099", source="android_call_screening")
        result = proc.process(ev)
        det = result["detection"]
        self.assertEqual(det["recommended_action"], "BLOCK")
        self.assertEqual(det["applied_action"], "ALLOW")
        self.assertEqual(det["mode"], "DRY_RUN")
        self.assertEqual(det["verdict"], "MALICIOUS")

    def test_incoming_call_unknown(self):
        proc = EventProcessor(self.cfg)
        ev = Event(event_type="INCOMING_CALL", number="+442071838750", source="android_call_screening")
        result = proc.process(ev)
        self.assertEqual(result["detection"]["verdict"], "UNKNOWN")
        self.assertEqual(result["detection"]["recommended_action"], "ALLOW")
        self.assertEqual(result["detection"]["applied_action"], "ALLOW")

    def test_invalid_number_returns_unknown_allow(self):
        proc = EventProcessor(self.cfg)
        ev = Event(event_type="INCOMING_CALL", number="not-a-number", source="android_call_screening")
        result = proc.process(ev)
        # Should be failed status but detection UNKNOWN/ALLOW
        self.assertEqual(result["detection"]["verdict"], "UNKNOWN")
        self.assertEqual(result["detection"]["applied_action"], "ALLOW")

    def test_screening_persistence(self):
        proc = EventProcessor(self.cfg)
        ev = Event(event_type="INCOMING_CALL", number="+919876543210", source="android_call_screening")
        proc.process(ev)
        events = self.db.recent_screening_events(limit=10)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["number"], "+919876543210")
        self.assertEqual(events[0]["applied_action"], "ALLOW")
        self.assertIn("number_masked", events[0])
        self.assertIn("number_hash", events[0])

    def test_dry_run_always_allow(self):
        # Even when we set screening_mode to ACTIVE (future), Phase 4 should still enforce DRY_RUN
        # Currently processor hardcodes DRY_RUN, so test that ACTIVE config still results in ALLOW
        self.cfg.screening_mode = "ACTIVE"
        proc = EventProcessor(self.cfg)
        self.db.upsert_list_entry("+919999900100", "blacklist", None, "2026-08-10T00:00:00Z")
        ev = Event(event_type="INCOMING_CALL", number="+919999900100", source="android_call_screening")
        result = proc.process(ev)
        self.assertEqual(result["detection"]["applied_action"], "ALLOW")
        self.assertEqual(result["screening"]["mode"], "DRY_RUN")


class TestScreeningMetrics(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_metrics(self):
        m = self.db.screening_metrics()
        self.assertEqual(m["total"], 0)
        proc = EventProcessor(self.cfg)
        ev = Event(event_type="INCOMING_CALL", number="+919876543210", source="android_call_screening")
        proc.process(ev)
        m2 = self.db.screening_metrics()
        self.assertEqual(m2["total"], 1)


class TestScreeningConfig(unittest.TestCase):
    def test_defaults(self):
        from callshield.config import Config
        cfg = Config()
        self.assertEqual(cfg.screening_mode, "DRY_RUN")
        self.assertEqual(cfg.screening_timeout_ms, 1500)
        self.assertTrue(cfg.screening_enabled)

    def test_validation(self):
        from callshield.config import Config, set_value
        from callshield.utils import ConfigError
        cfg = Config()
        with self.assertRaises(ConfigError):
            set_value(cfg, "screening_mode", "INVALID")
        with self.assertRaises(ConfigError):
            set_value(cfg, "screening_timeout_ms", "100")  # too low


if __name__ == "__main__":
    unittest.main()
