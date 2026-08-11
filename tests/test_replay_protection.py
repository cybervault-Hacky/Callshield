"""Phase 6 replay cache and fail-open daemon replay tests."""

import concurrent.futures
import time
import unittest
import uuid
from datetime import datetime, timezone

from callshield.daemon.service import DaemonService
from callshield.security import ReplayCache, ReplayStatus
from tests._common import IsolatedEnv


def timestamp(at=None):
    value = time.time() if at is None else at
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")


class TestReplayCache(unittest.TestCase):
    def test_duplicate_and_expired_requests(self):
        cache = ReplayCache(lifetime_seconds=300, max_entries=128)
        request_id = str(uuid.uuid4())
        self.assertEqual(
            cache.check_and_store(request_id, timestamp(), now=time.time()),
            ReplayStatus.ACCEPTED,
        )
        self.assertEqual(
            cache.check_and_store(request_id, timestamp(), now=time.time()),
            ReplayStatus.DUPLICATE,
        )
        self.assertEqual(
            cache.check_and_store(
                str(uuid.uuid4()), timestamp(time.time() - 301), now=time.time()
            ),
            ReplayStatus.EXPIRED,
        )

    def test_invalid_uuid_and_timestamp(self):
        cache = ReplayCache(lifetime_seconds=300, max_entries=128)
        self.assertEqual(
            cache.check_and_store("invalid", timestamp()), ReplayStatus.INVALID_ID
        )
        self.assertEqual(
            cache.check_and_store(str(uuid.uuid4()), "yesterday"),
            ReplayStatus.INVALID_TIMESTAMP,
        )

    def test_bounded_cache_and_expiration(self):
        now = time.time()
        cache = ReplayCache(lifetime_seconds=30, max_entries=128)
        for _ in range(200):
            cache.check_and_store(str(uuid.uuid4()), timestamp(now), now=now)
        self.assertEqual(cache.size(now=now), 128)
        self.assertEqual(cache.size(now=now + 31), 0)

    def test_thread_safe_duplicate_detection(self):
        cache = ReplayCache(lifetime_seconds=300, max_entries=128)
        request_id = str(uuid.uuid4())
        now = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            statuses = list(
                executor.map(
                    lambda _: cache.check_and_store(
                        request_id, timestamp(now), now=now
                    ),
                    range(10),
                )
            )
        self.assertEqual(statuses.count(ReplayStatus.ACCEPTED), 1)
        self.assertEqual(statuses.count(ReplayStatus.DUPLICATE), 9)


class TestDaemonReplayFailOpen(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(screening_enabled=True)
        self.service = DaemonService(self.cfg)

    def tearDown(self):
        self.env.stop()

    def test_duplicate_screening_returns_policy_error_allow(self):
        request = {
            "protocol": "callshield/1",
            "request_id": str(uuid.uuid4()),
            "timestamp": timestamp(),
            "number": "+919876543210",
            "source": "android_call_screening",
        }
        first = self.service._validate_and_dispatch(request)
        duplicate = self.service._validate_and_dispatch(request)
        self.assertEqual(first["applied_action"], "ALLOW")
        self.assertEqual(duplicate["reason"], "POLICY_ERROR")
        self.assertEqual(duplicate["applied_action"], "ALLOW")
        self.assertTrue(duplicate["policy_error"])
        self.assertEqual(duplicate["policy_error_detail"], "DUPLICATE_REQUEST")

    def test_persisted_request_is_rejected_after_daemon_restart(self):
        request = {
            "protocol": "callshield/1",
            "request_id": str(uuid.uuid4()),
            "timestamp": timestamp(),
            "number": "+919876543210",
            "source": "android_call_screening",
        }
        first = self.service._validate_and_dispatch(request)
        self.assertEqual(first["applied_action"], "ALLOW")
        restarted = DaemonService(self.cfg)
        replayed = restarted._validate_and_dispatch(request)
        self.assertEqual(replayed["reason"], "POLICY_ERROR")
        self.assertEqual(replayed["applied_action"], "ALLOW")
        self.assertEqual(
            replayed["policy_error_detail"], "DUPLICATE_PERSISTED_REQUEST"
        )

    def test_expired_active_request_returns_allow(self):
        request = {
            "protocol": "callshield/1",
            "request_id": str(uuid.uuid4()),
            "timestamp": timestamp(time.time() - 301),
            "number": "+919999900999",
            "source": "android_call_screening",
        }
        response = self.service._validate_and_dispatch(request)
        self.assertEqual(response["reason"], "POLICY_ERROR")
        self.assertEqual(response["applied_action"], "ALLOW")
        self.assertEqual(response["policy_error_detail"], "EXPIRED_REQUEST")


if __name__ == "__main__":
    unittest.main()
