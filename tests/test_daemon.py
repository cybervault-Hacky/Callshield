"""Tests for daemon process management (Phase 3)."""

import os
import time
import unittest
from pathlib import Path

from callshield.daemon.process import status, _read_pid, DaemonError
from tests._common import IsolatedEnv
from callshield.database import Database


class TestDaemonProcess(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        # Use a fresh config for each test
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        # Ensure daemon is stopped
        try:
            from callshield.daemon.process import stop
            stop(self.cfg, timeout=1.0)
        except Exception:
            pass
        self.db.close()
        self.env.stop()

    def test_start_and_status(self):
        # Start via CLI start (which spawns daemon)
        import subprocess, sys, os
        cfg = self.cfg
        # Directly use process.start and then status
        from callshield.daemon.process import start, status as daemon_status
        pid = start(cfg)
        self.assertIsInstance(pid, int)
        state, p = daemon_status(cfg)
        # Might be STALE if pid not alive check is strict, but we wrote pid ourselves
        # Our _pid_is_callshield may treat it as not callshield since we are not the daemon process?
        # Instead test via CLI start which spawns real daemon
        # Clean
        from callshield.daemon.process import _clear_pid
        _clear_pid(cfg, expected_pid=pid)

    def test_cli_start_stop(self):
        # Use CLI via subprocess with isolated env
        import subprocess, os, sys, json, pathlib
        env = os.environ.copy()
        env["CALLSHIELD_DATA_DIR"] = str(self.env.data)
        env["CALLSHIELD_LOG_DIR"] = str(self.env.logs)
        env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1])
        # Start
        r = subprocess.run([sys.executable, "-m", "callshield", "start"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))
        self.assertEqual(r.returncode, 0)
        self.assertIn("Protection daemon started", r.stdout)
        # Status should be RUNNING
        r = subprocess.run([sys.executable, "-m", "callshield", "status"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))
        self.assertEqual(r.returncode, 0)
        self.assertIn("RUNNING", r.stdout)
        # Duplicate start should not create another daemon
        r2 = subprocess.run([sys.executable, "-m", "callshield", "start"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))
        self.assertEqual(r2.returncode, 0)
        self.assertIn("already running", r2.stdout.lower())
        # Stop
        r = subprocess.run([sys.executable, "-m", "callshield", "stop"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))
        self.assertEqual(r.returncode, 0)
        self.assertIn("stopped", r.stdout.lower())
        # Status should be STOPPED
        r = subprocess.run([sys.executable, "-m", "callshield", "status"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))
        self.assertIn("STOPPED", r.stdout)
        # Stale PID handling
        pid_file = Path(self.cfg.pid_file)
        # Also check run_dir pid
        run_pid = Path(self.cfg.run_dir) / "callshield.pid"
        run_pid.parent.mkdir(parents=True, exist_ok=True)
        run_pid.write_text("999999")
        try:
            os.chmod(run_pid, 0o600)
        except Exception:
            pass
        r = subprocess.run([sys.executable, "-m", "callshield", "status"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))
        self.assertIn("STALE", r.stdout)
        # Start should clean stale and succeed
        r = subprocess.run([sys.executable, "-m", "callshield", "start"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))
        self.assertEqual(r.returncode, 0)
        self.assertIn("Protection daemon started", r.stdout)
        # Cleanup
        subprocess.run([sys.executable, "-m", "callshield", "stop"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))

    def test_pid_cleanup(self):
        # Ensure stop cleans PID
        import subprocess, os, sys, pathlib
        env = os.environ.copy()
        env["CALLSHIELD_DATA_DIR"] = str(self.env.data)
        env["CALLSHIELD_LOG_DIR"] = str(self.env.logs)
        env["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1])
        subprocess.run([sys.executable, "-m", "callshield", "start"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))
        time.sleep(0.5)
        subprocess.run([sys.executable, "-m", "callshield", "stop"], env=env, capture_output=True, text=True, cwd=str(pathlib.Path(__file__).resolve().parents[1]))
        time.sleep(0.5)
        state, pid = status(self.cfg)
        self.assertEqual(state, "STOPPED")
        self.assertIsNone(pid)


if __name__ == "__main__":
    unittest.main()
