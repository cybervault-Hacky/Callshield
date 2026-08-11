"""Phase 6 atomic configuration and safe reload tests."""

import json
import os
import threading
import unittest
from pathlib import Path
from unittest import mock

from callshield import config as config_module
from callshield.config import Config, config_integrity, load_config, save_config
from callshield.daemon.service import DaemonService
from callshield.utils import ConfigError, safe_write_text
from tests._common import IsolatedEnv


class TestConfigIntegrity(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.path = self.env.data / "config.json"
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def assert_safe(self, cfg):
        self.assertFalse(cfg.screening_enabled)
        self.assertEqual(cfg.screening_mode, "DRY_RUN")
        self.assertFalse(cfg.active_mode_confirmed)

    def test_empty_and_malformed_files_fail_safe(self):
        for content in ("", "   ", "{bad json", "[]"):
            with self.subTest(content=content):
                self.path.write_text(content, encoding="utf-8")
                cfg = load_config(self.path)
                self.assert_safe(cfg)
                self.assertTrue(getattr(cfg, "_config_integrity_error", None))
                with self.assertRaises(ConfigError):
                    load_config(self.path, strict=True)

    def test_invalid_active_and_threshold_values_fail_safe(self):
        self.path.write_text(
            json.dumps(
                {
                    "screening_enabled": True,
                    "screening_mode": "ACTIVE",
                    "active_mode_confirmed": True,
                    "balanced_active_block_threshold": 101,
                }
            ),
            encoding="utf-8",
        )
        cfg = load_config(self.path)
        self.assert_safe(cfg)
        self.assertIsNotNone(config_integrity(self.path))

    def test_atomic_write_permissions_and_no_temp_files(self):
        self.cfg.screening_enabled = False
        save_config(self.cfg, self.path)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.path.parent.glob(f".{self.path.name}.*.tmp")), [])
        loaded = load_config(self.path, strict=True)
        self.assertEqual(loaded.to_dict(), self.cfg.to_dict())

    def test_interrupted_replace_preserves_previous_config(self):
        save_config(self.cfg, self.path)
        previous = self.path.read_bytes()
        with mock.patch("os.replace", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                safe_write_text(self.path, "partial")
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.glob(f".{self.path.name}.*.tmp")), [])

    def test_file_and_directory_are_fsynced(self):
        calls = []
        real_fsync = os.fsync

        def recording_fsync(descriptor):
            calls.append(descriptor)
            return real_fsync(descriptor)

        with mock.patch("os.fsync", side_effect=recording_fsync):
            save_config(self.cfg, self.path)
        self.assertGreaterEqual(len(calls), 2)

    def test_concurrent_writes_leave_valid_complete_json(self):
        errors = []

        def writer(index):
            try:
                cfg = Config(default_country="US" if index % 2 else "IN")
                cfg.database_path = self.cfg.database_path
                cfg.pid_file = self.cfg.pid_file
                cfg.log_file = self.cfg.log_file
                cfg.run_dir = self.cfg.run_dir
                cfg.socket_path = self.cfg.socket_path
                cfg.daemon_log_file = self.cfg.daemon_log_file
                cfg.emergency_off_file = self.cfg.emergency_off_file
                save_config(cfg, self.path)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        loaded = load_config(self.path, strict=True)
        self.assertIn(loaded.default_country, ("IN", "US"))

    def test_invalid_sighup_reload_keeps_daemon_alive_and_fails_open(self):
        cfg = self.env.make_config(
            screening_enabled=True,
            screening_mode="ACTIVE",
            active_mode_confirmed=True,
        )
        service = DaemonService(cfg)
        self.path.write_text("{corrupt", encoding="utf-8")
        service._reload_config()
        self.assertFalse(service.cfg.screening_enabled)
        self.assertEqual(service.cfg.screening_mode, "DRY_RUN")
        self.assertFalse(service.cfg.active_mode_confirmed)
        self.assertEqual(service.processor.cfg.screening_mode, "DRY_RUN")
        self.assertEqual(service.health.snapshot()["config_integrity"], "ERROR")
        service.heartbeat.beat()
        self.assertTrue(service.heartbeat.is_fresh(max_age=5))


if __name__ == "__main__":
    unittest.main()
