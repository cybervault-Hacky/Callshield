"""Tests for process management specifics (Phase 3)."""

import os
import unittest
from pathlib import Path

from callshield.daemon.process import _pid_alive, _pid_is_callshield, _write_pid, _read_pid, _clear_pid, status
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


if __name__ == "__main__":
    unittest.main()
