"""Phase 4 Android screening bridge tests (DRY_RUN / fail-open only)."""

import concurrent.futures
import sqlite3
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

from callshield.config import Config, set_value
from callshield.daemon.service import DaemonService
from callshield.database import Database
from callshield.events import Event
from callshield.events.processor import EventProcessor
from callshield.events.types import SOURCE_ANDROID
from callshield.utils import ConfigError
from tests._common import IsolatedEnv, run_cli


def android_request(number="+919876543210", **overrides):
    request = {
        "protocol": "callshield/1",
        "request_id": str(uuid.uuid4()),
        "number": number,
        "source": "android_call_screening",
    }
    request.update(overrides)
    return request


class TestScreeningProcessor(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(screening_enabled=True)
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_valid_incoming_call_is_advisory(self):
        result = EventProcessor(self.cfg).process(
            Event(
                event_type="INCOMING_CALL",
                number="+442071838750",
                source=SOURCE_ANDROID,
            )
        )
        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["detection"]["applied_action"], "ALLOW")
        self.assertEqual(result["screening"]["mode"], "DRY_RUN")

    def test_invalid_and_missing_numbers_fail_open(self):
        processor = EventProcessor(self.cfg)
        for number in ("not-a-number", "", None):
            with self.subTest(number=number):
                result = processor.process(
                    Event(
                        event_type="INCOMING_CALL",
                        number=number,
                        source=SOURCE_ANDROID,
                    )
                )
                self.assertEqual(result["status"], "processed")
                self.assertEqual(result["detection"]["verdict"], "UNKNOWN")
                self.assertEqual(result["detection"]["applied_action"], "ALLOW")

    def test_block_recommendation_still_applies_allow(self):
        number = "+919999900099"
        self.db.upsert_list_entry(
            number, "blacklist", "test", "2026-08-11T00:00:00+00:00"
        )
        result = EventProcessor(self.cfg).process(
            Event(
                event_type="INCOMING_CALL",
                number=number,
                source=SOURCE_ANDROID,
            )
        )
        self.assertEqual(result["detection"]["recommended_action"], "BLOCK")
        self.assertEqual(result["detection"]["applied_action"], "ALLOW")
        self.assertEqual(result["screening"]["reason"], "DRY_RUN")


class TestScreeningService(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(screening_enabled=True)
        self.db = Database(self.cfg.database_path)
        self.service = DaemonService(self.cfg)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_exact_android_request_low_risk(self):
        number = "+919999900201"
        self.db.upsert_list_entry(
            number, "whitelist", "safe", "2026-08-11T00:00:00+00:00"
        )
        response = self.service._handle_screening_request(android_request(number))
        self.assertEqual(response["protocol"], "callshield/1")
        self.assertEqual(response["recommended_action"], "ALLOW")
        self.assertEqual(response["applied_action"], "ALLOW")
        self.assertEqual(response["mode"], "DRY_RUN")

    def test_high_risk_recommends_block_but_applies_allow(self):
        number = "+919999900200"
        self.db.upsert_list_entry(
            number, "blacklist", "fraud", "2026-08-11T00:00:00+00:00"
        )
        response = self.service._handle_screening_request(android_request(number))
        self.assertEqual(response["verdict"], "MALICIOUS")
        self.assertEqual(response["recommended_action"], "BLOCK")
        self.assertEqual(response["applied_action"], "ALLOW")
        self.assertEqual(response["reason"], "DRY_RUN")

    def test_invalid_null_protocol_source_and_id_fail_open(self):
        requests = (
            android_request("not-a-number"),
            android_request(None),
            android_request(protocol="other/1"),
            android_request(source="unexpected"),
            android_request(request_id="invalid"),
        )
        for request in requests:
            with self.subTest(request=request):
                response = self.service._handle_screening_request(request)
                self.assertEqual(response["verdict"], "UNKNOWN")
                self.assertEqual(response["applied_action"], "ALLOW")
                self.assertEqual(response["mode"], "DRY_RUN")

    def test_screening_disabled_fails_open(self):
        self.service.cfg.screening_enabled = False
        response = self.service._handle_screening_request(android_request())
        self.assertEqual(response["reason"], "SCREENING_DISABLED")
        self.assertEqual(response["applied_action"], "ALLOW")

    def test_timeout_fails_open_and_is_persisted_once(self):
        self.service.cfg.screening_timeout_ms = 200

        def slow_processor(_event):
            time.sleep(0.3)
            return {
                "status": "processed",
                "detection": {
                    "risk_score": 0,
                    "confidence": 0,
                    "verdict": "UNKNOWN",
                    "recommended_action": "ALLOW",
                },
                "screening": {"reason": "late"},
            }

        self.service.processor.process = slow_processor
        response = self.service._handle_screening_request(android_request())
        self.assertEqual(response["reason"], "SCREENING_TIMEOUT")
        self.assertEqual(response["applied_action"], "ALLOW")
        time.sleep(0.15)
        rows = self.db.recent_screening_events()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "SCREENING_TIMEOUT")

    def test_internal_exception_fails_open(self):
        self.service.processor.process = mock.Mock(side_effect=RuntimeError("boom"))
        response = self.service._handle_screening_request(android_request())
        self.assertEqual(response["reason"], "INTERNAL_ERROR")
        self.assertEqual(response["applied_action"], "ALLOW")

    def test_database_persistence_failure_still_allows(self):
        with mock.patch.object(
            self.service, "_persist_screening_result", return_value=False
        ):
            response = self.service._handle_screening_request(android_request())
        self.assertEqual(response["applied_action"], "ALLOW")
        self.assertGreaterEqual(self.service.health.snapshot()["bridge_errors"], 1)

    def test_persistence_masks_hashes_and_never_blocks(self):
        request = android_request()
        response = self.service._handle_screening_request(request)
        row = self.db.recent_screening_events(limit=1)[0]
        self.assertEqual(row["event_id"], request["request_id"])
        self.assertNotEqual(row["number_masked"], row["number"])
        self.assertEqual(len(row["number_hash"]), 64)
        self.assertEqual(row["applied_action"], "ALLOW")
        self.assertEqual(row["mode"], "DRY_RUN")
        self.assertEqual(response["applied_action"], "ALLOW")

    def test_health_metrics_include_zero_blocked(self):
        self.service._handle_screening_request(android_request("not-a-number"))
        snapshot = self.service.health.snapshot()
        self.assertEqual(snapshot["incoming_calls"], 1)
        self.assertEqual(snapshot["screened"], 1)
        self.assertEqual(snapshot["screening_allowed"], 1)
        self.assertEqual(snapshot["screening_unknown"], 1)
        self.assertEqual(snapshot["screening_blocked"], 0)


class TestScreeningConcurrency(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(screening_enabled=True)
        self.service = DaemonService(self.cfg)

    def tearDown(self):
        self.env.stop()

    def test_multiple_simultaneous_requests(self):
        original_weights = dict(self.cfg.signal_weights)
        requests = [android_request(f"+91987654{i:04d}") for i in range(8)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            responses = list(executor.map(self.service._handle_screening_request, requests))
        self.assertEqual(len(responses), 8)
        self.assertTrue(all(item["applied_action"] == "ALLOW" for item in responses))
        self.assertTrue(all(item["mode"] == "DRY_RUN" for item in responses))
        self.assertEqual(self.cfg.signal_weights, original_weights)
        metrics = Database(self.cfg.database_path)
        try:
            self.assertEqual(metrics.screening_metrics()["screening_blocked"], 0)
            self.assertEqual(metrics.count_screening_events(), 8)
        finally:
            metrics.close()


class TestScreeningDatabase(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_v2_to_v3_migration_preserves_settings(self):
        path = Path(self.cfg.database_path)
        path.unlink(missing_ok=True)
        connection = sqlite3.connect(str(path))
        connection.executescript(
            """
            CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
            INSERT INTO schema_version(version) VALUES (2);
            CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO settings(key, value) VALUES ('preserved', 'yes');
            """
        )
        connection.close()
        database = Database(path)
        try:
            version = database._conn.execute(
                "SELECT version FROM schema_version"
            ).fetchone()[0]
            self.assertEqual(version, 5)
            self.assertEqual(database.get_setting("preserved"), "yes")
            self.assertEqual(database.count_screening_events(), 0)
        finally:
            database.close()

    def test_database_rejects_non_allow_applied_action(self):
        database = Database(self.cfg.database_path)
        try:
            with self.assertRaises(ValueError):
                database.add_screening_event(
                    timestamp="2026-08-11T00:00:00+00:00",
                    number="+919876543210",
                    risk_score=100,
                    confidence=100,
                    verdict="MALICIOUS",
                    recommended_action="BLOCK",
                    applied_action="BLOCK",
                    reason="invalid",
                    latency_ms=1,
                    source=SOURCE_ANDROID,
                    event_id=str(uuid.uuid4()),
                )
            self.assertEqual(database.count_screening_events(), 0)
        finally:
            database.close()


class TestScreeningConfigAndCLI(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_defaults_and_timeout_validation(self):
        cfg = Config()
        self.assertFalse(cfg.screening_enabled)
        self.assertEqual(cfg.screening_mode, "DRY_RUN")
        self.assertFalse(cfg.active_mode_confirmed)
        self.assertEqual(cfg.screening_timeout_ms, 1500)
        with self.assertRaises(ConfigError):
            set_value(cfg, "screening_timeout_ms", "100")
        with self.assertRaises(ConfigError):
            set_value(cfg, "screening_timeout_ms", "5001")

    def test_invalid_loaded_screening_config_falls_back(self):
        cfg = Config.from_dict(
            {
                "screening_enabled": "invalid",
                "screening_mode": "ACTIVE",
                "screening_timeout_ms": 100,
            }
        )
        self.assertFalse(cfg.screening_enabled)
        self.assertEqual(cfg.screening_mode, "DRY_RUN")
        self.assertEqual(cfg.screening_timeout_ms, 1500)

    def test_active_mode_is_rejected(self):
        with self.assertRaises(ConfigError):
            set_value(Config(), "screening_mode", "ACTIVE")

    def test_screening_cli_commands_when_stopped(self):
        for arguments, expected in (
            (("screening", "status"), "Android:             NOT VERIFIED"),
            (("screening", "mode"), "DRY_RUN"),
            (("screening", "health"), "Applied Blocks:      0"),
            (("screening", "metrics"), "Actually Rejected:   0"),
            (("screening", "disable"), "Screening Enabled:   NO"),
            (("screening", "enable"), "Screening Enabled:   YES"),
        ):
            with self.subTest(arguments=arguments):
                code, output = run_cli(self.cfg, *arguments)
                self.assertEqual(code, 0)
                self.assertIn(expected, output)

    def test_screening_cli_defaults_active_confirmation_to_no(self):
        code, output = run_cli(self.cfg, "screening", "mode", "ACTIVE")
        self.assertEqual(code, 0)
        self.assertIn("was not enabled", output)
        self.assertEqual(self.cfg.screening_mode, "DRY_RUN")
        self.assertFalse(self.cfg.screening_enabled)


if __name__ == "__main__":
    unittest.main()
