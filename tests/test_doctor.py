"""Phase 6 doctor diagnostics, repair, and masked block inspection tests."""

import json
import os
import unittest
import uuid
from pathlib import Path

from callshield import config as config_module
from callshield.config import load_config
from callshield.database import Database
from callshield.doctor import ERROR, run_doctor
from callshield.utils import iso_now
from tests._common import IsolatedEnv, run_cli


class TestDoctor(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        for directory in (
            self.env.root,
            self.env.data,
            self.env.logs,
            Path(self.cfg.run_dir),
            Path(self.cfg.run_dir).parent / "state",
        ):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)

    def tearDown(self):
        self.env.stop()

    def test_doctor_works_with_stopped_daemon(self):
        report = run_doctor(self.cfg, repair=True)
        self.assertNotEqual(report.status, ERROR)
        names = {check.name for check in report.checks}
        self.assertTrue(
            {
                "Runtime",
                "Python",
                "Database",
                "Schema",
                "Config",
                "Daemon",
                "IPC",
                "Permissions",
                "Android Bridge",
                "Screening",
                "Policy",
                "Storage",
            }.issubset(names)
        )

    def test_json_cli_output(self):
        code, output = run_cli(self.cfg, "doctor", "--json", "--repair")
        self.assertEqual(code, 0)
        parsed = json.loads(output)
        self.assertIn(parsed["status"], ("HEALTHY", "WARNING"))
        self.assertIsInstance(parsed["checks"], list)

    def test_repair_cleans_stale_pid_and_corrects_permissions(self):
        pid_path = Path(self.cfg.pid_file)
        pid_path.write_text("999999", encoding="utf-8")
        pid_path.chmod(0o644)
        config_path = Path(config_module.CONFIG_PATH)
        config_path.chmod(0o644)
        report = run_doctor(self.cfg, repair=True)
        self.assertFalse(pid_path.exists())
        self.assertEqual(config_path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(any(check.repaired for check in report.checks))
        self.assertFalse(self.cfg.screening_enabled)
        self.assertEqual(self.cfg.screening_mode, "DRY_RUN")

    def test_corrupt_config_is_reported_and_runtime_config_is_safe(self):
        Path(config_module.CONFIG_PATH).write_text("{corrupt", encoding="utf-8")
        safe = load_config(config_module.CONFIG_PATH)
        report = run_doctor(safe)
        config_check = next(check for check in report.checks if check.name == "Config")
        self.assertEqual(config_check.status, ERROR)
        self.assertFalse(safe.screening_enabled)
        self.assertEqual(safe.screening_mode, "DRY_RUN")


class TestBlockInspection(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        database = Database(self.cfg.database_path)
        try:
            self.block_id = database.add_screening_event(
                timestamp=iso_now(),
                number="+919876543210",
                risk_score=95,
                confidence=95,
                verdict="MALICIOUS",
                recommended_action="BLOCK",
                applied_action="BLOCK",
                reason="ACTIVE_POLICY_BLOCK",
                latency_ms=4,
                source="android_call_screening",
                event_id=str(uuid.uuid4()),
                mode="ACTIVE",
                policy_action="BLOCK",
                policy_name="BALANCED",
                threshold=85,
                confidence_threshold=80,
                policy_reason="ACTIVE_POLICY_BLOCK",
                emergency_off=False,
            )
        finally:
            database.close()

    def tearDown(self):
        self.env.stop()

    def test_blocks_list_is_masked(self):
        code, output = run_cli(self.cfg, "blocks")
        self.assertEqual(code, 0)
        self.assertNotIn("+919876543210", output)
        self.assertIn("3210", output)

    def test_blocks_inspect_is_masked_and_complete(self):
        code, output = run_cli(self.cfg, "blocks", "inspect", str(self.block_id))
        self.assertEqual(code, 0)
        self.assertNotIn("+919876543210", output)
        for label in (
            "Timestamp:",
            "Risk:",
            "Confidence:",
            "Policy:",
            "Recommendation:",
            "Applied Action:",
            "Reason:",
            "Confirmation:",
        ):
            self.assertIn(label, output)


if __name__ == "__main__":
    unittest.main()
