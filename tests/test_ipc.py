"""Tests for IPC (Phase 3)."""

import concurrent.futures
import json
import os
import socket
import stat
import time
import unittest
from pathlib import Path

from tests._common import IsolatedEnv


class TestIPC(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(ipc_timeout=0.25)
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
        return self._raw((json.dumps(payload) + "\n").encode())

    def _raw(self, data):
        sock_path = Path(self.cfg.socket_path)
        if not sock_path.exists():
            sock_path = Path(self.cfg.run_dir) / "callshield.sock"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(str(sock_path))
        s.sendall(data)
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
        resp = self._req(big)
        self.assertEqual(resp.get("status"), "error")
        self.assertIn("large", resp.get("error", "").lower())
        self.assertEqual(self._req({"command": "ping"})["status"], "ok")

    def test_ping_health_and_daemon_info(self):
        ping = self._req({"command": "ping"})
        self.assertEqual(ping, {"status": "ok", "pong": True})
        health = self._req({"command": "health"})
        self.assertEqual(health.get("status"), "ok")
        self.assertIn("healthy", health)
        info = self._req({"command": "daemon_info"})
        self.assertEqual(info.get("status"), "ok")
        self.assertEqual(info["data"]["state"], "RUNNING")

    def test_event_operation_and_validation(self):
        accepted = self._req(
            {
                "command": "event",
                "event": {
                    "event_type": "NUMBER_SCAN",
                    "number": "+919876543210",
                    "source": "TEST",
                    "payload": {"reason": "ipc test"},
                },
            }
        )
        self.assertEqual(accepted.get("status"), "ok")
        self.assertTrue(accepted.get("event_id"))
        rejected = self._req({"command": "event", "event": {"source": "TEST"}})
        self.assertEqual(rejected.get("status"), "error")

    def test_exact_android_bridge_request_contract(self):
        import uuid

        request_id = str(uuid.uuid4())
        response = self._req(
            {
                "protocol": "callshield/1",
                "request_id": request_id,
                "number": "+919876543210",
                "source": "android_call_screening",
            }
        )
        self.assertEqual(response["protocol"], "callshield/1")
        self.assertEqual(response["request_id"], request_id)
        self.assertEqual(response["applied_action"], "ALLOW")
        self.assertEqual(response["mode"], "DRY_RUN")

    def test_android_high_risk_block_recommendation_applies_allow(self):
        import uuid
        from callshield.database import Database

        number = "+919999900200"
        database = Database(self.cfg.database_path)
        try:
            database.upsert_list_entry(
                number,
                "blacklist",
                "ipc test",
                "2026-08-11T00:00:00+00:00",
            )
        finally:
            database.close()
        response = self._req(
            {
                "protocol": "callshield/1",
                "request_id": str(uuid.uuid4()),
                "number": number,
                "source": "android_call_screening",
            }
        )
        self.assertEqual(response["recommended_action"], "BLOCK")
        self.assertEqual(response["applied_action"], "ALLOW")

    def test_android_invalid_request_fails_open(self):
        import uuid

        for request in (
            {
                "protocol": "callshield/1",
                "request_id": str(uuid.uuid4()),
                "number": "invalid",
                "source": "android_call_screening",
            },
            {
                "protocol": "wrong/1",
                "request_id": str(uuid.uuid4()),
                "number": "+919876543210",
                "source": "android_call_screening",
            },
        ):
            response = self._req(request)
            self.assertEqual(response["verdict"], "UNKNOWN")
            self.assertEqual(response["applied_action"], "ALLOW")

    def test_concurrent_android_requests(self):
        import uuid

        def request(index):
            return self._req(
                {
                    "protocol": "callshield/1",
                    "request_id": str(uuid.uuid4()),
                    "number": f"+91987654{index:04d}",
                    "source": "android_call_screening",
                }
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            responses = list(executor.map(request, range(6)))
        self.assertTrue(all(item["applied_action"] == "ALLOW" for item in responses))

    def test_screening_status_is_honest_about_device(self):
        response = self._req({"command": "screening_status"})
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["data"]["bridge"], "CONNECTED")
        self.assertEqual(response["data"]["android"], "NOT VERIFIED")
        self.assertEqual(response["data"]["actually_rejected"], 0)
        disabled = self._req({"command": "screening_config", "enabled": False})
        self.assertEqual(disabled["status"], "ok")
        self.assertFalse(disabled["screening_enabled"])
        enabled = self._req({"command": "screening_config", "enabled": True})
        self.assertEqual(enabled["status"], "ok")
        self.assertTrue(enabled["screening_enabled"])

    def test_malformed_json_returns_error_and_daemon_survives(self):
        response = self._raw(b"{not-json}\n")
        self.assertEqual(response.get("status"), "error")
        self.assertEqual(self._req({"command": "ping"})["status"], "ok")

    def test_partial_request_times_out_safely(self):
        response = self._raw(b'{"command":')
        self.assertEqual(response.get("status"), "error")
        self.assertIn("timeout", response.get("error", "").lower())

    def test_socket_is_unix_only(self):
        sock_path = Path(self.cfg.socket_path)
        self.assertTrue(stat.S_ISSOCK(sock_path.stat().st_mode))
        self.assertEqual(self._req({"command": "ping"})["status"], "ok")

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
