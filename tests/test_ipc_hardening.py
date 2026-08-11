"""Phase 6 strict Unix IPC parsing and bounds tests."""

import json
import socket
import time
import unittest
import uuid

from callshield.daemon.service import (
    MAX_IPC_REQUEST,
    MAX_IPC_RESPONSE,
    DaemonService,
)
from callshield.utils import iso_now
from tests._common import IsolatedEnv


class TestIPCHardening(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.service = DaemonService(self.cfg)

    def tearDown(self):
        self.env.stop()

    def envelope(self, **values):
        request = {
            "protocol": "callshield/1",
            "request_id": str(uuid.uuid4()),
            "timestamp": iso_now(),
            "command": "ping",
        }
        request.update(values)
        return request

    def read_raw(self, value):
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.sendall(value)
            return self.service._read_ipc_request(server)
        finally:
            client.close()
            server.close()

    def test_strict_json_rejects_duplicate_keys(self):
        raw = (
            '{"protocol":"callshield/1","protocol":"other",'
            '"request_id":"%s","timestamp":"%s","command":"ping"}\n'
            % (uuid.uuid4(), iso_now())
        ).encode()
        with self.assertRaises(ValueError):
            self.read_raw(raw)

    def test_rejects_excessive_nesting(self):
        nested = "[" * 18 + "0" + "]" * 18
        raw = (
            '{"protocol":"callshield/1","request_id":"%s",'
            '"timestamp":"%s","command":"ping","data":%s}\n'
            % (uuid.uuid4(), iso_now(), nested)
        ).encode()
        with self.assertRaises(ValueError):
            self.read_raw(raw)

    def test_rejects_oversized_request(self):
        request = self.envelope(data="x" * MAX_IPC_REQUEST)
        raw = (json.dumps(request) + "\n").encode()
        self.assertGreater(len(raw), MAX_IPC_REQUEST)
        with self.assertRaises(ValueError):
            self.read_raw(raw)

    def test_protocol_and_command_allowlist(self):
        invalid_protocol = self.service._validate_and_dispatch(
            self.envelope(protocol="other/1")
        )
        self.assertEqual(invalid_protocol["error"], "POLICY_ERROR")
        unknown = self.service._validate_and_dispatch(
            self.envelope(command="not_allowed")
        )
        self.assertEqual(unknown["status"], "error")
        self.assertIn("Unknown command", unknown["error"])

    def test_invalid_timestamp_is_policy_error(self):
        response = self.service._validate_and_dispatch(
            self.envelope(timestamp="invalid")
        )
        self.assertEqual(response["status"], "error")
        self.assertEqual(response["detail"], "INVALID_TIMESTAMP")

    def test_response_is_bounded(self):
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.service._send_ipc_response(server, {"data": "x" * MAX_IPC_RESPONSE})
            response = client.recv(4096)
            self.assertLessEqual(len(response), MAX_IPC_RESPONSE)
            self.assertIn(b"Response too large", response)
        finally:
            client.close()
            server.close()

    def test_disconnected_client_is_isolated(self):
        server, client = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        client.close()
        # No exception should escape a disconnected client handler.
        self.service._handle_ipc_conn(server)

    def test_configured_timeout_is_bounded(self):
        self.assertGreaterEqual(self.cfg.ipc_timeout, 0.1)
        self.assertLessEqual(self.cfg.ipc_timeout, 30.0)
        self.assertEqual(self.cfg.ipc_timeout, 1.5)


if __name__ == "__main__":
    unittest.main()
