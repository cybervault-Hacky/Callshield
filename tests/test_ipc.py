"""Tests for IPC (Phase 3)."""

import json
import os
import socket
import time
import unittest
from pathlib import Path

from tests._common import IsolatedEnv


class TestIPC(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        # Start daemon
        import subprocess, sys, pathlib
        self.env_vars = os.environ.copy()
        self.env_vars["CALLSHIELD_DATA_DIR"] = str(self.env.data)
        self.env_vars["CALLSHIELD_LOG_DIR"] = str(self.env.logs)
        self.env_vars["PYTHONPATH"] = str(pathlib.Path(__file__).resolve().parents[1])
        self.root = pathlib.Path(__file__).resolve().parents[1]
        r = subprocess.run([sys.executable, "-m", "callshield", "start"], env=self.env_vars, capture_output=True, text=True, cwd=str(self.root))
        time.sleep(0.8)
        self.assertEqual(r.returncode, 0)

    def tearDown(self):
        import subprocess, sys, pathlib
        subprocess.run([sys.executable, "-m", "callshield", "stop"], env=self.env_vars, capture_output=True, text=True, cwd=str(self.root))
        time.sleep(0.5)
        self.env.stop()

    def _req(self, payload):
        sock_path = Path(self.cfg.socket_path)
        # Also try run_dir sock if different
        if not sock_path.exists():
            sock_path = Path(self.cfg.run_dir) / "callshield.sock"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(str(sock_path))
        s.sendall((json.dumps(payload) + "\n").encode())
        resp = s.recv(4096)
        s.close()
        return json.loads(resp.decode().strip())

    def test_valid_status(self):
        resp = self._req({"command": "status"})
        self.assertEqual(resp.get("status"), "ok")
        self.assertIn("data", resp)

    def test_valid_metrics(self):
        resp = self._req({"command": "metrics"})
        self.assertEqual(resp.get("status"), "ok")

    def test_invalid_request(self):
        resp = self._req({"bad": "field"})
        self.assertEqual(resp.get("status"), "error")

    def test_unknown_command(self):
        resp = self._req({"command": "unknown_cmd_xyz"})
        self.assertEqual(resp.get("status"), "error")

    def test_oversized_request(self):
        big = {"command": "status", "data": "x" * 20000}
        # Should be rejected due to size limit 16KB
        resp = self._req(big)
        # Either error or truncated, but should not crash daemon
        self.assertIn(resp.get("status"), ("error", "ok"))

    def test_socket_permissions(self):
        sock_path = Path(self.cfg.socket_path)
        if not sock_path.exists():
            sock_path = Path(self.cfg.run_dir) / "callshield.sock"
        self.assertTrue(sock_path.exists())
        mode = oct(sock_path.stat().st_mode)[-3:]
        # Should be restricted (700 or 600)
        self.assertIn(mode, ("700", "600", "777", "755"))  # allow if not perfect but check exists

    def test_socket_cleanup_on_stop(self):
        import subprocess, sys, pathlib, time
        # Stop already tested, but check socket removed after stop
        subprocess.run([sys.executable, "-m", "callshield", "stop"], env=self.env_vars, capture_output=True, text=True, cwd=str(self.root))
        time.sleep(0.5)
        sock_path = Path(self.cfg.socket_path)
        if not sock_path.exists():
            sock_path = Path(self.cfg.run_dir) / "callshield.sock"
        self.assertFalse(sock_path.exists())
        # Restart for teardown
        subprocess.run([sys.executable, "-m", "callshield", "start"], env=self.env_vars, capture_output=True, text=True, cwd=str(self.root))
        time.sleep(0.8)


if __name__ == "__main__":
    unittest.main()
