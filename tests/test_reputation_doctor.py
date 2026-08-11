"""Phase 7 doctor reputation/trust diagnostics."""

import unittest

from callshield.database import Database
from callshield.doctor import ERROR, HEALTHY, run_doctor
from callshield.reputation import ReputationEngine
from tests._common import IsolatedEnv
from tests._reputation import analysis, measured_signal


class TestReputationDoctor(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        for path in (self.env.data, self.env.logs):
            path.chmod(0o700)

    def tearDown(self):
        self.env.stop()

    def test_doctor_reports_reputation_components(self):
        report = run_doctor(self.cfg, repair=True)
        checks = {check.name: check for check in report.checks}
        for name in (
            "Reputation Database",
            "Reputation Schema",
            "Reputation Integrity",
            "Trust Database",
        ):
            self.assertIn(name, checks)
            self.assertEqual(checks[name].status, HEALTHY)

    def test_doctor_detects_corrupt_reputation_json(self):
        db = Database(self.cfg.database_path)
        try:
            ReputationEngine(db, self.cfg).calculate(
                "+919876543210",
                analysis=analysis(70, 80, [measured_signal()]),
            )
            with db.transaction():
                db._conn.execute(
                    "UPDATE reputation_profiles SET reasons_json='not-json'"
                )
        finally:
            db.close()
        report = run_doctor(self.cfg)
        check = next(
            item for item in report.checks if item.name == "Reputation Integrity"
        )
        self.assertEqual(check.status, ERROR)
        self.assertEqual(report.status, ERROR)


if __name__ == "__main__":
    unittest.main()
