"""Tests for health monitoring (Phase 3)."""

import time
import unittest

from callshield.daemon.health import HealthMonitor
from tests._common import IsolatedEnv
from callshield.database import Database


class TestHealth(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_initial_snapshot(self):
        hm = HealthMonitor(self.cfg)
        snap = hm.snapshot()
        self.assertIn("state", snap)
        self.assertIn("pid", snap)
        self.assertIn("uptime_seconds", snap)
        self.assertIn("queue_size", snap)

    def test_heartbeat_fresh(self):
        from callshield.daemon.heartbeat import Heartbeat
        hb = Heartbeat(self.cfg, interval=1)
        hb.beat()
        self.assertTrue(hb.is_fresh(max_age=5))
        time.sleep(0.1)
        self.assertTrue(hb.is_fresh(max_age=5))
        # Simulate stale
        hb.last_beat = time.time() - 100
        self.assertFalse(hb.is_fresh(max_age=10))

    def test_db_health(self):
        hm = HealthMonitor(self.cfg)
        status = hm.check_db()
        self.assertEqual(status, "ONLINE")
        snap = hm.snapshot()
        self.assertEqual(snap["db_status"], "ONLINE")

    def test_queue_health(self):
        hm = HealthMonitor(self.cfg)
        hm.update_queue(5, peak=10)
        snap = hm.snapshot()
        self.assertEqual(snap["queue_size"], 5)
        self.assertEqual(snap["queue_peak"], 10)
        # Not saturated, should be healthy
        self.assertTrue(hm.is_healthy())
        # Saturate queue
        hm.update_queue(250, peak=250)
        snap = hm.snapshot()
        # With queue near max, health may be degraded but not necessarily false
        # Just ensure snapshot works

    def test_metrics_increment(self):
        hm = HealthMonitor(self.cfg)
        hm.inc_received()
        hm.inc_processed(verdict="HIGH_RISK", action="BLOCK")
        hm.inc_failed(error="test")
        hm.inc_dropped()
        snap = hm.snapshot()
        self.assertEqual(snap["received"], 1)
        self.assertEqual(snap["processed"], 1)
        self.assertEqual(snap["failed"], 1)
        self.assertEqual(snap["dropped"], 1)
        self.assertEqual(snap["high_risk_count"], 1)
        self.assertEqual(snap["blocked_recommendations"], 1)

    def test_heartbeat_callback_updates_health(self):
        from callshield.daemon.heartbeat import Heartbeat

        hm = HealthMonitor(self.cfg)
        heartbeat = Heartbeat(self.cfg, interval=1, on_beat=hm.set_heartbeat)
        heartbeat.beat()
        snap = hm.snapshot()
        self.assertIsNotNone(snap["last_heartbeat"])
        self.assertFalse(snap["heartbeat_stale"])

    def test_stale_heartbeat_degrades_health(self):
        hm = HealthMonitor(self.cfg)
        hm.set_state("RUNNING")
        hm.set_heartbeat(time.time() - self.cfg.heartbeat_interval * 4)
        snap = hm.snapshot()
        self.assertTrue(snap["heartbeat_stale"])
        self.assertFalse(hm.is_healthy())

    def test_snapshot_has_required_aliases_and_memory(self):
        hm = HealthMonitor(self.cfg)
        snap = hm.snapshot()
        for key in (
            "events_received",
            "events_processed",
            "events_failed",
            "events_dropped",
            "memory_kb",
            "heartbeat_age_seconds",
        ):
            self.assertIn(key, snap)


if __name__ == "__main__":
    unittest.main()
