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
            create_event("UNSUPPORTED_EVENT", number="+919876543210")

    def test_phase4_incoming_call_type(self):
        from callshield.events.types import SOURCE_ANDROID

        event = create_event(
            "INCOMING_CALL",
            number="+919876543210",
            source=SOURCE_ANDROID,
        )
        self.assertEqual(event.event_type, "INCOMING_CALL")
        self.assertEqual(event.source, "android_call_screening")

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

    def test_event_id_must_be_uuid(self):
        with self.assertRaises(ValueError):
            Event(event_id="not-a-uuid", event_type="SYSTEM")

    def test_timestamp_must_be_timezone_aware_iso(self):
        with self.assertRaises(ValueError):
            Event(event_type="SYSTEM", timestamp="yesterday")
        with self.assertRaises(ValueError):
            Event(event_type="SYSTEM", timestamp="2026-08-11T12:00:00")

    def test_payload_uses_utf8_byte_limit(self):
        # 2,100 emoji are fewer than 8,192 characters but exceed 8 KiB UTF-8.
        with self.assertRaises(ValueError):
            Event(event_type="SYSTEM", payload={"value": "😀" * 2100})

    def test_payload_must_be_json_serializable(self):
        with self.assertRaises(ValueError):
            Event(event_type="SYSTEM", payload={"bad": {1, 2, 3}})

    def test_from_dict_does_not_coerce_malformed_payload(self):
        with self.assertRaises(ValueError):
            Event.from_dict(
                {
                    "event_type": "SYSTEM",
                    "timestamp": "2026-08-11T12:00:00Z",
                    "source": "TEST",
                    "payload": [],
                }
            )


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

    def test_action_events_are_advisory_records_only(self):
        proc = EventProcessor(self.cfg)
        number = "+919876543210"
        for event_type in ("BLOCK_ACTION", "ALLOW_ACTION"):
            result = proc.process(
                create_event(event_type, number=number, source="TEST")
            )
            self.assertEqual(result["status"], "processed")
        # Neither event mutates the user's blacklist or whitelist.
        self.assertIsNone(self.db.get_list_entry(number, "blacklist"))
        self.assertIsNone(self.db.get_list_entry(number, "whitelist"))

    def test_configured_payload_limit_is_rechecked(self):
        self.cfg.event_payload_limit = 256
        proc = EventProcessor(self.cfg)
        event = create_event(
            "NUMBER_SCAN", number="+919876543210", payload={"x": "y" * 300}
        )
        with self.assertRaises(ValueError):
            proc.process(event)


if __name__ == "__main__":
    unittest.main()
