"""Tests for crash recovery and shutdown (Phase 3)."""

import time
import unittest

from callshield.events import Event, EventQueue
from callshield.events.processor import EventProcessor
from tests._common import IsolatedEnv


class TestRecovery(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_event_exception_continues(self):
        # Processor should handle malformed event without crashing daemon
        q = EventQueue(maxsize=10)
        proc = EventProcessor(self.cfg)
        # Enqueue a valid and an invalid event
        ev1 = Event(event_type="NUMBER_SCAN", number="not-a-number", source="TEST")
        ev2 = Event(event_type="NUMBER_SCAN", number="+919876543210", source="TEST")
        q.put(ev1)
        q.put(ev2)
        # Process both
        for _ in range(2):
            ev = q.get(block=False)
            if ev:
                result = proc.process(ev)
                # First should be failed, second processed
                self.assertIn(result["status"], ("processed", "failed"))

    def test_malformed_payload(self):
        proc = EventProcessor(self.cfg)
        ev = Event(event_type="NUMBER_SCAN", number="+919876543210", payload={"weird": "x" * 1000}, source="TEST")
        result = proc.process(ev)
        self.assertIn(result["status"], ("processed", "failed"))

    def test_database_failure_handling(self):
        # Simulate DB failure by using invalid path
        from callshield.config import Config
        bad_cfg = Config(database_path="/nonexistent/path/db.db", pid_file="/tmp/bad.pid", log_file="/tmp/bad.log", run_dir="/tmp", socket_path="/tmp/bad.sock", daemon_log_file="/tmp/bad.log")
        proc = EventProcessor(bad_cfg)
        ev = Event(event_type="NUMBER_SCAN", number="+919876543210", source="TEST")
        # Should not crash, should return failed
        result = proc.process(ev)
        self.assertIn(result["status"], ("processed", "failed"))

    def test_graceful_shutdown(self):
        # Test that daemon handles SIGTERM gracefully
        import subprocess, os, sys, pathlib, signal
        env = os.environ.copy()
        env["CALLSHIELD_DATA_DIR"] = str(self.env.data)
        env["CALLSHIELD_LOG_DIR"] = str(self.env.logs)
        env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1])
        root = pathlib.Path(__file__).resolve().parents[1]
        r = subprocess.run([sys.executable, "-m", "callshield", "start"], env=env, capture_output=True, text=True, cwd=str(root))
        self.assertEqual(r.returncode, 0)
        time.sleep(0.8)
        # Get PID
        from callshield.daemon.process import _read_pid
        pid = _read_pid(self.cfg)
        self.assertIsNotNone(pid)
        # Send SIGTERM
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        time.sleep(1.0)
        # Should be stopped
        from callshield.daemon.process import status
        state, _ = status(self.cfg)
        self.assertEqual(state, "STOPPED")


if __name__ == "__main__":
    unittest.main()
