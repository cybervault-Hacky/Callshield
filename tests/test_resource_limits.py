"""Phase 6 bounded-resource regression tests."""

import unittest

from callshield.daemon.service import (
    MAX_IPC_REQUEST,
    MAX_IPC_RESPONSE,
    MAX_IPC_WORKERS,
    DaemonService,
)
from callshield.events import Event, EventQueue
from callshield.events.models import MAX_PAYLOAD_SIZE
from callshield.security import ReplayCache
from tests._common import IsolatedEnv


class TestResourceLimits(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_established_limits(self):
        self.assertEqual(self.cfg.event_queue_size, 256)
        self.assertEqual(MAX_PAYLOAD_SIZE, 8 * 1024)
        self.assertEqual(MAX_IPC_REQUEST, 16 * 1024)
        self.assertEqual(MAX_IPC_RESPONSE, 64 * 1024)
        self.assertEqual(self.cfg.replay_cache_size, 4096)

    def test_queue_never_exceeds_bound(self):
        queue = EventQueue(maxsize=16)
        for _ in range(100):
            queue.enqueue(Event(event_type="SYSTEM"))
        self.assertEqual(queue.size(), 16)
        self.assertEqual(queue.metrics()["dropped"], 84)

    def test_payload_utf8_size_is_bounded(self):
        with self.assertRaises(ValueError):
            Event(event_type="SYSTEM", payload={"value": "😀" * 3000})

    def test_replay_cache_never_exceeds_bound(self):
        import time
        import uuid
        from datetime import datetime, timezone

        cache = ReplayCache(lifetime_seconds=300, max_entries=128)
        now = time.time()
        timestamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
        for _ in range(1000):
            cache.check_and_store(str(uuid.uuid4()), timestamp, now=now)
        self.assertEqual(cache.size(now=now), 128)

    def test_concurrent_ipc_slots_are_bounded(self):
        service = DaemonService(self.cfg)
        acquired = [
            service._ipc_client_slots.acquire(blocking=False)
            for _ in range(MAX_IPC_WORKERS + 1)
        ]
        self.assertEqual(acquired.count(True), MAX_IPC_WORKERS)
        self.assertFalse(acquired[-1])
        for success in acquired:
            if success:
                service._ipc_client_slots.release()


if __name__ == "__main__":
    unittest.main()
