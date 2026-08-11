"""Phase 5 active screening, persistence, feedback, and safety tests."""

import concurrent.futures
import sqlite3
import unittest
import uuid
from pathlib import Path

from callshield.daemon.service import DaemonService
from callshield.database import Database
from callshield.policy import enable_emergency_off
from tests._common import IsolatedEnv


def request(number):
    return {
        "protocol": "callshield/1",
        "request_id": str(uuid.uuid4()),
        "number": number,
        "source": "android_call_screening",
    }


def feedback(screening_request_id):
    from callshield.utils import iso_now

    return {
        "command": "screening_feedback",
        "protocol": "callshield/1",
        "request_id": str(uuid.uuid4()),
        "timestamp": iso_now(),
        "screening_request_id": screening_request_id,
        "source": "android_call_screening",
        "result": "REJECTED",
    }


class TestActiveScreeningService(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(
            screening_enabled=True,
            screening_mode="ACTIVE",
            active_mode_confirmed=True,
            screening_policy="BALANCED",
        )
        self.db = Database(self.cfg.database_path)
        self.service = DaemonService(self.cfg)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def blacklist(self, number):
        self.db.upsert_list_entry(
            number, "blacklist", "phase5 test", "2026-08-11T00:00:00+00:00"
        )

    def whitelist(self, number):
        self.db.upsert_list_entry(
            number, "whitelist", "phase5 safe", "2026-08-11T00:00:00+00:00"
        )

    def test_active_policy_applies_block(self):
        number = "+919999900301"
        self.blacklist(number)
        response = self.service._handle_screening_request(request(number))
        self.assertEqual(response["recommended_action"], "BLOCK")
        self.assertEqual(response["applied_action"], "BLOCK")
        self.assertEqual(response["mode"], "ACTIVE")
        self.assertEqual(response["policy_name"], "BALANCED")
        row = self.db.recent_screening_events(limit=1)[0]
        self.assertEqual(row["policy_action"], "BLOCK")
        self.assertEqual(row["applied_action"], "BLOCK")
        self.assertEqual(row["actually_rejected"], 0)

    def test_dry_run_recommends_block_applies_allow(self):
        self.service.cfg.screening_mode = "DRY_RUN"
        self.service.cfg.active_mode_confirmed = False
        self.service.processor.cfg = self.service.cfg
        number = "+919999900302"
        self.blacklist(number)
        response = self.service._handle_screening_request(request(number))
        self.assertEqual(response["recommended_action"], "BLOCK")
        self.assertEqual(response["applied_action"], "ALLOW")
        self.assertEqual(response["mode"], "DRY_RUN")

    def test_whitelist_absolute_override_in_active_mode(self):
        number = "+919999900303"
        self.blacklist(number)
        self.whitelist(number)
        response = self.service._handle_screening_request(request(number))
        self.assertEqual(response["recommended_action"], "ALLOW")
        self.assertEqual(response["applied_action"], "ALLOW")
        self.assertEqual(response["reason"], "WHITELIST_OVERRIDE")

    def test_emergency_off_forces_allow(self):
        number = "+919999900304"
        self.blacklist(number)
        enable_emergency_off(self.cfg)
        response = self.service._handle_screening_request(request(number))
        self.assertEqual(response["recommended_action"], "BLOCK")
        self.assertEqual(response["applied_action"], "ALLOW")
        self.assertEqual(response["reason"], "EMERGENCY_OFF")
        self.assertTrue(response["emergency_off"])

    def test_final_boundary_rejects_invalid_block_pair(self):
        response = {
            "protocol": "callshield/1",
            "request_id": str(uuid.uuid4()),
            "risk_score": 100,
            "confidence": 100,
            "verdict": "MALICIOUS",
            "recommended_action": "BLOCK",
            "applied_action": "BLOCK",
            "mode": "DRY_RUN",
            "reason": "invalid",
            "latency_ms": 1,
            "policy_name": "BALANCED",
            "threshold": 85,
            "confidence_threshold": 80,
            "emergency_off": False,
            "policy_error": False,
        }
        finalized = self.service._finalize_screening(response, "+919876543210")
        self.assertEqual(finalized["applied_action"], "ALLOW")
        self.assertEqual(finalized["reason"], "SAFETY_FALLBACK")

    def test_actual_rejection_requires_feedback(self):
        number = "+919999900305"
        self.blacklist(number)
        response = self.service._handle_screening_request(request(number))
        before = self.db.screening_metrics()
        self.assertEqual(before["screening_blocked"], 1)
        self.assertEqual(before["actually_rejected"], 0)
        acknowledged = self.service._validate_and_dispatch(
            feedback(response["request_id"])
        )
        self.assertEqual(acknowledged["status"], "ok")
        self.assertTrue(acknowledged["confirmed"])
        after = self.db.screening_metrics()
        self.assertEqual(after["actually_rejected"], 1)
        duplicate = self.service._validate_and_dispatch(
            feedback(response["request_id"])
        )
        self.assertFalse(duplicate["confirmed"])
        self.assertEqual(self.db.screening_metrics()["actually_rejected"], 1)

    def test_feedback_cannot_confirm_allow(self):
        response = self.service._handle_screening_request(request("+442071838750"))
        acknowledged = self.service._validate_and_dispatch(
            feedback(response["request_id"])
        )
        self.assertEqual(acknowledged["status"], "ok")
        self.assertFalse(acknowledged["confirmed"])
        self.assertEqual(self.db.screening_metrics()["actually_rejected"], 0)

    def test_malformed_feedback_fails_open(self):
        response = self.service._validate_and_dispatch(
            {
                "command": "screening_feedback",
                "protocol": "bad",
                "request_id": "bad",
                "source": "unexpected",
                "result": "REJECTED",
            }
        )
        self.assertEqual(response["status"], "error")
        self.assertEqual(self.db.screening_metrics()["actually_rejected"], 0)

    def test_concurrent_active_requests_remain_policy_bounded(self):
        numbers = [f"+91999991{index:04d}" for index in range(6)]
        for number in numbers:
            self.blacklist(number)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            responses = list(
                executor.map(
                    self.service._handle_screening_request,
                    [request(number) for number in numbers],
                )
            )
        self.assertTrue(
            all(item["applied_action"] in ("ALLOW", "BLOCK") for item in responses)
        )
        self.assertTrue(
            all(
                item["applied_action"] != "BLOCK" or item["mode"] == "ACTIVE"
                for item in responses
            )
        )
        self.assertEqual(self.db.screening_metrics()["actually_rejected"], 0)


class TestPhase5DatabaseMigration(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_v3_to_v4_preserves_dry_run_rows(self):
        path = Path(self.cfg.database_path)
        path.unlink(missing_ok=True)
        connection = sqlite3.connect(str(path))
        connection.executescript(
            """
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version(version) VALUES (3);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE screening_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                number TEXT NOT NULL,
                number_masked TEXT NOT NULL,
                number_hash TEXT NOT NULL,
                risk INTEGER NOT NULL,
                confidence INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                recommended_action TEXT NOT NULL,
                applied_action TEXT NOT NULL,
                reason TEXT,
                latency_ms INTEGER NOT NULL,
                source TEXT NOT NULL,
                event_id TEXT NOT NULL,
                mode TEXT NOT NULL
            );
            INSERT INTO screening_events
                (timestamp,number,number_masked,number_hash,risk,confidence,
                 verdict,recommended_action,applied_action,reason,latency_ms,
                 source,event_id,mode)
            VALUES ('2026-08-11T00:00:00Z','+919876543210','+91******3210',
                    'hash',90,90,'MALICIOUS','BLOCK','ALLOW','DRY_RUN',5,
                    'android_call_screening','00000000-0000-4000-8000-000000000001',
                    'DRY_RUN');
            """
        )
        connection.close()
        database = Database(path)
        try:
            version = database._conn.execute(
                "SELECT version FROM schema_version"
            ).fetchone()[0]
            self.assertEqual(version, 7)
            row = database.recent_screening_events(limit=1)[0]
            self.assertEqual(row["applied_action"], "ALLOW")
            self.assertEqual(row["policy_action"], "BLOCK")
            self.assertEqual(row["policy_name"], "BALANCED")
            self.assertEqual(row["actually_rejected"], 0)
        finally:
            database.close()


if __name__ == "__main__":
    unittest.main()
