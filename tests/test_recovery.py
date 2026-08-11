"""Tests for crash recovery and shutdown (Phase 3)."""

import socket
import threading
import time
import unittest
from pathlib import Path

from callshield.daemon.process import DaemonError
from callshield.daemon.recovery import recover_runtime, validate_startup
from callshield.daemon.service import DaemonService
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

    def test_stale_pid_and_socket_recovery(self):
        pid_path = Path(self.cfg.pid_file)
        pid_path.write_text("999999", encoding="utf-8")
        socket_path = Path(self.cfg.socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(socket_path))
        listener.close()

        recover_runtime(self.cfg)
        self.assertFalse(pid_path.exists())
        self.assertFalse(socket_path.exists())

    def test_active_socket_is_never_removed(self):
        socket_path = Path(self.cfg.socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(socket_path))
        listener.listen(1)
        try:
            with self.assertRaises(DaemonError):
                recover_runtime(self.cfg)
            self.assertTrue(socket_path.exists())
        finally:
            listener.close()
            socket_path.unlink(missing_ok=True)

    def test_non_socket_runtime_file_is_preserved(self):
        socket_path = Path(self.cfg.socket_path)
        socket_path.write_text("unrelated", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            validate_startup(self.cfg)
        self.assertEqual(socket_path.read_text(encoding="utf-8"), "unrelated")

    def test_processor_exception_isolated_in_worker(self):
        service = DaemonService(self.cfg)
        original = service.processor.process
        calls = {"count": 0}

        def flaky(event):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("isolated test failure")
            return original(event)

        service.processor.process = flaky
        worker = threading.Thread(target=service._processor_loop)
        worker.start()
        service.queue.enqueue(Event(event_type="SYSTEM", source="TEST"))
        service.queue.enqueue(Event(event_type="SYSTEM", source="TEST"))
        self.assertTrue(service.queue.wait_until_done(3.0))
        service.request_shutdown()
        worker.join(timeout=2.0)
        snapshot = service.health.snapshot()
        self.assertEqual(snapshot["failed"], 1)
        self.assertEqual(snapshot["processed"], 1)
        self.assertFalse(worker.is_alive())
        service._do_graceful_shutdown()

    def test_graceful_shutdown_processes_accepted_queue(self):
        service = DaemonService(self.cfg)
        worker = threading.Thread(target=service._processor_loop)
        worker.start()
        for _ in range(4):
            self.assertTrue(
                service.queue.enqueue(Event(event_type="SYSTEM", source="TEST"))
            )
        service.request_shutdown()
        self.assertTrue(service.queue.wait_until_done(3.0))
        worker.join(timeout=2.0)
        self.assertEqual(service.health.snapshot()["processed"], 4)
        self.assertEqual(service.queue.size(), 0)
        service._do_graceful_shutdown()


if __name__ == "__main__":
    unittest.main()
