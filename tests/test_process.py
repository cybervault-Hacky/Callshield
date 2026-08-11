"""Tests for process management specifics (Phase 3)."""

import os
import socket
import subprocess
import sys
import unittest
from pathlib import Path

from callshield.daemon.process import (
    DaemonError,
    _clear_pid,
    _clear_socket,
    _pid_alive,
    _pid_is_callshield,
    _read_pid,
    _write_pid,
    status,
    stop,
)
from tests._common import IsolatedEnv


class TestProcessManagement(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_pid_alive(self):
        self.assertTrue(_pid_alive(os.getpid()))
        self.assertFalse(_pid_alive(999999))

    def test_write_and_read_pid(self):
        pid = _write_pid(self.cfg)
        self.assertEqual(pid, os.getpid())
        read = _read_pid(self.cfg)
        self.assertEqual(read, pid)
        _clear_pid(self.cfg, expected_pid=pid)
        self.assertIsNone(_read_pid(self.cfg))

    def test_clear_with_expected(self):
        pid = _write_pid(self.cfg)
        # Try clear with wrong expected should not delete
        _clear_pid(self.cfg, expected_pid=pid+1)
        self.assertIsNotNone(_read_pid(self.cfg))
        _clear_pid(self.cfg, expected_pid=pid)
        self.assertIsNone(_read_pid(self.cfg))

    def test_status_stopped(self):
        state, pid = status(self.cfg)
        self.assertEqual(state, "STOPPED")
        self.assertIsNone(pid)

    def test_stale_detection(self):
        run_pid = Path(self.cfg.run_dir) / "callshield.pid"
        run_pid.parent.mkdir(parents=True, exist_ok=True)
        run_pid.write_text("999999")
        state, pid = status(self.cfg)
        self.assertEqual(state, "STALE")
        self.assertEqual(pid, 999999)

    def test_malformed_pid_is_stale(self):
        Path(self.cfg.pid_file).write_text("not-a-pid", encoding="utf-8")
        self.assertEqual(status(self.cfg), ("STALE", None))

    def test_atomic_duplicate_pid_claim_rejected(self):
        pid = _write_pid(self.cfg)
        with self.assertRaises(DaemonError):
            _write_pid(self.cfg)
        _clear_pid(self.cfg, expected_pid=pid)

    def test_unrelated_python_process_is_never_signalled(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        )
        try:
            Path(self.cfg.pid_file).write_text(str(process.pid), encoding="utf-8")
            self.assertFalse(_pid_is_callshield(process.pid))
            self.assertEqual(status(self.cfg), ("STALE", process.pid))
            stopped, pid = stop(self.cfg, timeout=0.1)
            self.assertFalse(stopped)
            self.assertEqual(pid, process.pid)
            self.assertIsNone(process.poll())
        finally:
            process.terminate()
            process.wait(timeout=3)

    def test_stale_socket_cleanup_is_type_safe(self):
        path = Path(self.cfg.socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        listener.close()
        self.assertTrue(_clear_socket(self.cfg))
        self.assertFalse(path.exists())

        path.write_text("unrelated", encoding="utf-8")
        self.assertFalse(_clear_socket(self.cfg))
        self.assertEqual(path.read_text(encoding="utf-8"), "unrelated")

    def test_active_socket_is_preserved(self):
        path = Path(self.cfg.socket_path)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        listener.listen(1)
        try:
            self.assertFalse(_clear_socket(self.cfg))
            self.assertTrue(path.exists())
        finally:
            listener.close()
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
