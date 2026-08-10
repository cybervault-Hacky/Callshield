import json
import unittest

from callshield.database import Database
from callshield.detector import analyze_number
from callshield.utils import iso_now
from tests._common import IsolatedEnv, run_cli


class TestReports(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_report_creates_record(self):
        code, _out = run_cli(self.cfg, "report", "+919999988888", "--reason", "suspected scam")
        self.assertEqual(code, 0)
        self.assertEqual(self.db.count_reports("+919999988888"), 1)

    def test_multiple_reports_accumulate(self):
        run_cli(self.cfg, "report", "+919999988888", "--reason", "spam")
        run_cli(self.cfg, "report", "+919999988888", "--reason", "scam")
        self.assertEqual(self.db.count_reports("+919999988888"), 2)

    def test_report_invalid_number(self):
        code, _out = run_cli(self.cfg, "report", "not-a-number")
        self.assertNotEqual(code, 0)

    def test_report_adds_signal(self):
        self.db.add_report("+919999977777", "spam call", iso_now())
        r = analyze_number(
            "+919999977777", db=self.db, cfg=self.cfg, record_event=False
        )
        self.assertTrue(any(s["name"] == "manual_user_report" for s in r.signals))


class TestJSONOutput(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_scan_json_output(self):
        code, out = run_cli(self.cfg, "scan", "+442071838750", "--json", "--no-log")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["number"], "+442071838750")
        self.assertIn("risk_score", data)
        self.assertIn("confidence", data)
        self.assertIn("reputation", data)
        self.assertIn("signals", data)
        self.assertIn("recommended_action", data)

    def test_scan_quiet_prints_only_action(self):
        code, out = run_cli(self.cfg, "scan", "+442071838750", "--quiet", "--no-log")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "ALLOW")


if __name__ == "__main__":
    unittest.main()
