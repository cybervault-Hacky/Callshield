"""Phase 6 simultaneous Unix IPC and replay-race tests."""

import concurrent.futures
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

from callshield.utils import iso_now
from tests._common import IsolatedEnv


class TestConcurrentIPC(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(screening_enabled=True)
        self.root = Path(__file__).resolve().parents[1]
        self.environment = os.environ.copy()
        self.environment["CALLSHIELD_DATA_DIR"] = str(self.env.data)
        self.environment["CALLSHIELD_LOG_DIR"] = str(self.env.logs)
        self.environment["PYTHONPATH"] = str(self.root)
        result = subprocess.run(
            [sys.executable, "-m", "callshield", "daemon", "start"],
            cwd=str(self.root),
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def tearDown(self):
        subprocess.run(
            [sys.executable, "-m", "callshield", "daemon", "stop"],
            cwd=str(self.root),
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.env.stop()

    def send(self, payload):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(3)
        client.connect(self.cfg.socket_path)
        client.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        data = b""
        while b"\n" not in data:
            data += client.recv(4096)
        client.close()
        return json.loads(data.split(b"\n", 1)[0])

    def request(self, index):
        return {
            "protocol": "callshield/1",
            "request_id": str(uuid.uuid4()),
            "timestamp": iso_now(),
            "number": f"+9198765{index:05d}",
            "source": "android_call_screening",
        }

    def run_unique(self, count):
        requests = [self.request(index) for index in range(count)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as executor:
            responses = list(executor.map(self.send, requests))
        self.assertEqual(
            {item["request_id"] for item in responses},
            {item["request_id"] for item in requests},
        )
        self.assertTrue(all(item["applied_action"] == "ALLOW" for item in responses))
        return responses

    def test_five_concurrent_requests(self):
        self.assertEqual(len(self.run_unique(5)), 5)

    def test_ten_concurrent_requests(self):
        self.assertEqual(len(self.run_unique(10)), 10)

    def test_concurrent_duplicate_is_applied_at_most_once(self):
        request = self.request(99)
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            responses = list(executor.map(lambda _: self.send(request), range(10)))
        accepted = [item for item in responses if item.get("reason") != "POLICY_ERROR"]
        replayed = [item for item in responses if item.get("reason") == "POLICY_ERROR"]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(replayed), 9)
        self.assertTrue(all(item["applied_action"] == "ALLOW" for item in responses))
        ping = self.send(
            {
                "protocol": "callshield/1",
                "request_id": str(uuid.uuid4()),
                "timestamp": iso_now(),
                "command": "ping",
            }
        )
        self.assertTrue(ping["pong"])


if __name__ == "__main__":
    unittest.main()
