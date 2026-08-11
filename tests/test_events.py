"""Tests for event model and processor (Phase 3)."""

import unittest

from callshield.events import Event, create_event, EventQueue
from callshield.events.types import VALID_EVENT_TYPES
from callshield.events.processor import EventProcessor
from callshield.config import Config
from callshield.database import Database
from tests._common import IsolatedEnv


class TestEventModel(unittest.TestCase):
    def test_create_valid(self):
        ev = create_event("NUMBER_SCAN", number="+919876543210", source="TEST")
        self.assertEqual(ev.event_type, "NUMBER_SCAN")
        self.assertEqual(ev.number, "+919876543210")
        self.assertTrue(ev.event_id)

    def test_invalid_type(self):
        with self.assertRaises(ValueError):
            create_event("FAKE_EVENT", number="+919876543210")

    def test_from_dict(self):
        data = {
            "event_type": "USER_REPORT",
            "timestamp": "2026-08-10T12:00:00Z",
            "source": "CLI",
            "number": "+919876543210",
            "payload": {"reason": "spam"},
        }
        ev = Event.from_dict(data)
        self.assertEqual(ev.event_type, "USER_REPORT")
        self.assertEqual(ev.payload["reason"], "spam")

    def test_payload_size_limit(self):
        big = {"data": "x" * 9000}
        with self.assertRaises(ValueError):
            Event(event_type="NUMBER_SCAN", number="+919876543210", payload=big)

    def test_event_types(self):
        for t in VALID_EVENT_TYPES:
            ev = create_event(t, number="+919876543210" if t not in ("SYSTEM", "HEARTBEAT") else None)
            self.assertEqual(ev.event_type, t)


class TestEventProcessor(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_process_number_scan(self):
        proc = EventProcessor(self.cfg)
        ev = create_event("NUMBER_SCAN", number="+919876543210", source="TEST")
        result = proc.process(ev)
        self.assertEqual(result["status"], "processed")
        self.assertIn("detection", result)
        self.assertEqual(result["detection"]["number"], "+919876543210")

    def test_process_invalid_number(self):
        proc = EventProcessor(self.cfg)
        ev = create_event("NUMBER_SCAN", number="not-a-number", source="TEST")
        result = proc.process(ev)
        self.assertEqual(result["status"], "failed")
        self.assertIsNotNone(result["error"])

    def test_process_system_event(self):
        proc = EventProcessor(self.cfg)
        ev = create_event("SYSTEM", source="SYSTEM")
        result = proc.process(ev)
        self.assertEqual(result["status"], "processed")

    def test_process_missing_number(self):
        proc = EventProcessor(self.cfg)
        ev = Event(event_type="NUMBER_SCAN", source="TEST", number=None, payload={})
        result = proc.process(ev)
        self.assertEqual(result["status"], "failed")

    def test_process_malformed_payload(self):
        proc = EventProcessor(self.cfg)
        ev = create_event("NUMBER_SCAN", number="+919876543210")
        # Processor should not crash on weird payload
        ev.payload = {"number": "+919876543210", "extra": "x" * 100}
        result = proc.process(ev)
        self.assertIn(result["status"], ("processed", "failed"))


if __name__ == "__main__":
    unittest.main()
