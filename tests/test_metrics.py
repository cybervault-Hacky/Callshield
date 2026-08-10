"""Tests for metrics (Phase 3)."""

import time
import unittest

from tests._common import IsolatedEnv


class TestMetrics(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_metrics_via_cli(self):
        import subprocess, os, sys, pathlib, json
        env = os.environ.copy()
        env["CALLSHIELD_DATA_DIR"] = str(self.env.data)
        env["CALLSHIELD_LOG_DIR"] = str(self.env.logs)
        env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1])
        root = pathlib.Path(__file__).resolve().parents[1]
        # Start daemon
        subprocess.run([sys.executable, "-m", "callshield", "start"], env=env, capture_output=True, text=True, cwd=str(root))
        time.sleep(0.8)
        # Metrics should be empty initially
        r = subprocess.run([sys.executable, "-m", "callshield", "metrics"], env=env, capture_output=True, text=True, cwd=str(root))
        self.assertEqual(r.returncode, 0)
        self.assertIn("Uptime", r.stdout)
        self.assertIn("Events Received", r.stdout)
        # Send test event
        r = subprocess.run([sys.executable, "-m", "callshield", "event", "test", "+919876543210"], env=env, capture_output=True, text=True, cwd=str(root))
        self.assertEqual(r.returncode, 0)
        time.sleep(0.6)
        r = subprocess.run([sys.executable, "-m", "callshield", "metrics"], env=env, capture_output=True, text=True, cwd=str(root))
        self.assertIn("Events Received", r.stdout)
        # Check that received increased
        # Stop
        subprocess.run([sys.executable, "-m", "callshield", "stop"], env=env, capture_output=True, text=True, cwd=str(root))
        time.sleep(0.5)

    def test_health_monitor_metrics(self):
        from callshield.daemon.health import HealthMonitor
        hm = HealthMonitor(self.cfg)
        hm.inc_received()
        hm.inc_processed(verdict="HIGH_RISK", action="BLOCK")
        hm.inc_failed(error="test")
        snap = hm.snapshot()
        self.assertEqual(snap["received"], 1)
        self.assertEqual(snap["processed"], 1)
        self.assertEqual(snap["failed"], 1)


if __name__ == "__main__":
    unittest.main()
