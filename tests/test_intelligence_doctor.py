"""Phase 8 doctor intelligence diagnostics and non-fabrication tests."""

import unittest

from callshield.adaptive import BehaviorEngine
from callshield.database import Database
from callshield.doctor import ERROR, HEALTHY, run_doctor
from tests._adaptive import observation, reputation
from tests._common import IsolatedEnv


class TestIntelligenceDoctor(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.env.data.chmod(0o700)
        self.env.logs.chmod(0o700)

    def tearDown(self):
        self.env.stop()

    def test_doctor_reports_all_intelligence_checks(self):
        report = run_doctor(self.cfg, repair=True)
        checks = {item.name: item for item in report.checks}
        for name in (
            "Intelligence Database",
            "Intelligence Schema",
            "Intelligence Integrity",
            "Intelligence Storage",
            "Intelligence Retention",
        ):
            self.assertIn(name, checks)
            self.assertEqual(checks[name].status, HEALTHY)

    def test_corrupt_snapshot_is_reported(self):
        db = Database(self.cfg.database_path)
        try:
            engine = BehaviorEngine(db, self.cfg)
            engine.snapshot(
                "+919876543210",
                reputation=reputation("+919876543210", score=60),
                observation=observation(1, 60),
            )
            with db.transaction():
                db._conn.execute(
                    "UPDATE intelligence_profiles SET snapshot_json='not-json'"
                )
        finally:
            db.close()
        report = run_doctor(self.cfg)
        check = next(
            item for item in report.checks if item.name == "Intelligence Integrity"
        )
        self.assertEqual(check.status, ERROR)
        self.assertEqual(report.status, ERROR)

    def test_doctor_repair_never_changes_policy_or_fabricates_data(self):
        self.cfg.screening_enabled = False
        self.cfg.screening_mode = "DRY_RUN"
        before = self.cfg.to_dict()
        report = run_doctor(self.cfg, repair=True)
        self.assertNotEqual(report.status, ERROR)
        self.assertEqual(self.cfg.screening_enabled, before["screening_enabled"])
        self.assertEqual(self.cfg.screening_mode, before["screening_mode"])
        db = Database(self.cfg.database_path)
        try:
            count = db._conn.execute(
                "SELECT COUNT(*) FROM intelligence_observations"
            ).fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
