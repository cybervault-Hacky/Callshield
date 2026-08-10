import unittest

from callshield.database import Database
from callshield.detector import analyze_number
from callshield.utils import iso_now
from tests._common import IsolatedEnv


class TestSignals(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_blacklist_signal_fires(self):
        self.db.upsert_list_entry("+919999911111", "blacklist", None, iso_now())
        r = analyze_number("+919999911111", db=self.db, cfg=self.cfg, record_event=False)
        self.assertTrue(any(s["name"] == "blacklist_match" for s in r.signals))

    def test_whitelist_signal_fires(self):
        self.db.upsert_list_entry("+919999922222", "whitelist", None, iso_now())
        r = analyze_number("+919999922222", db=self.db, cfg=self.cfg, record_event=False)
        self.assertTrue(any(s["name"] == "whitelist_match" for s in r.signals))

    def test_list_conflict_signal_fires(self):
        self.db.upsert_list_entry("+919999933333", "blacklist", None, iso_now())
        self.db.upsert_list_entry("+919999933333", "whitelist", None, iso_now())
        r = analyze_number("+919999933333", db=self.db, cfg=self.cfg, record_event=False)
        self.assertTrue(any(s["name"] == "list_conflict" for s in r.signals))

    def test_reports_signal_fires_after_report(self):
        self.db.add_report("+919999944444", "suspected scam", iso_now())
        r = analyze_number("+919999944444", db=self.db, cfg=self.cfg, record_event=False)
        self.assertTrue(any(s["name"] == "manual_user_report" for s in r.signals))

    def test_unknown_number_has_no_strong_signals(self):
        # Fresh number; must NOT trigger blacklist/whitelist/report signals.
        r = analyze_number("+442071838750", db=self.db, cfg=self.cfg, record_event=False)
        names = {s["name"] for s in r.signals}
        self.assertNotIn("blacklist_match", names)
        self.assertNotIn("whitelist_match", names)
        self.assertNotIn("manual_user_report", names)


if __name__ == "__main__":
    unittest.main()
