"""Tests for bounded event queue (Phase 3)."""

import unittest
import time

from callshield.events import EventQueue, Event


class TestEventQueue(unittest.TestCase):
    def test_enqueue_dequeue(self):
        q = EventQueue(maxsize=10)
        ev = Event(event_type="NUMBER_SCAN", number="+919876543210")
        self.assertTrue(q.put(ev))
        self.assertEqual(q.qsize(), 1)
        out = q.get(block=False)
        self.assertEqual(out.event_id, ev.event_id)

    def test_queue_full(self):
        q = EventQueue(maxsize=2)
        for i in range(2):
            ev = Event(event_type="NUMBER_SCAN", number=f"+91987654321{i}")
            self.assertTrue(q.put(ev))
        # Next should fail (full)
        ev3 = Event(event_type="NUMBER_SCAN", number="+919876543219")
        self.assertFalse(q.put(ev3))
        self.assertEqual(q.metrics()["dropped"], 1)
        self.assertEqual(q.qsize(), 2)

    def test_thread_safe(self):
        import threading
        q = EventQueue(maxsize=50)
        def producer():
            for i in range(20):
                ev = Event(event_type="NUMBER_SCAN", number=f"+9198765432{i:02d}")
                q.put(ev)
        threads = [threading.Thread(target=producer) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # Should have 50 max, but at least some dropped due to bound
        self.assertLessEqual(q.qsize(), 50)

    def test_invalid_event(self):
        q = EventQueue(maxsize=10)
        with self.assertRaises(ValueError):
            q.put("not an event")  # type: ignore

    def test_close(self):
        q = EventQueue(maxsize=10)
        q.close()
        self.assertTrue(q.is_closed())
        ev = Event(event_type="NUMBER_SCAN", number="+919876543210")
        self.assertFalse(q.put(ev))

    def test_metrics(self):
        q = EventQueue(maxsize=5)
        for i in range(3):
            q.put(Event(event_type="NUMBER_SCAN", number=f"+9198765432{i}"))
        m = q.metrics()
        self.assertEqual(m["received"], 3)
        self.assertEqual(m["size"], 3)
        self.assertGreaterEqual(m["peak"], 3)


if __name__ == "__main__":
    unittest.main()
