import unittest

from callshield.database import Database
from callshield.utils import iso_now
from tests._common import IsolatedEnv


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.db = Database(self.env.data / "test.db")

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_initialization_creates_tables(self):
        cur = self.db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {r["name"] for r in cur.fetchall()}
        self.assertIn("numbers", names)
        self.assertIn("events", names)
        self.assertIn("settings", names)

    def test_upsert_and_lookup(self):
        n = "+919876543210"
        res = self.db.upsert_list_entry(n, "blacklist", "test", iso_now())
        self.assertEqual(res, "inserted")
        row = self.db._get_number_in_list(n, "blacklist")
        self.assertIsNotNone(row)
        self.assertEqual(row["list_type"], "blacklist")

    def test_upsert_duplicate_is_idempotent(self):
        n = "+919876543210"
        self.db.upsert_list_entry(n, "blacklist", "first", iso_now())
        res = self.db.upsert_list_entry(n, "blacklist", "second", iso_now())
        self.assertEqual(res, "exists")
        self.assertEqual(len(self.db.list_numbers("blacklist")), 1)

    def test_remove(self):
        n = "+919876543210"
        self.db.upsert_list_entry(n, "blacklist", None, iso_now())
        self.assertTrue(self.db.remove_from_list(n, "blacklist"))
        self.assertIsNone(self.db._get_number_in_list(n, "blacklist"))
        self.assertFalse(self.db.remove_from_list(n, "blacklist"))

    def test_coexist_in_both_lists_reports_conflict(self):
        n = "+919876543210"
        self.db.upsert_list_entry(n, "blacklist", None, iso_now())
        res = self.db.upsert_list_entry(n, "whitelist", None, iso_now())
        self.assertEqual(res, "inserted")
        all_rows = self.db.list_numbers()
        types = sorted(r["list_type"] for r in all_rows if r["number"] == n)
        self.assertEqual(types, ["blacklist", "whitelist"])

    def test_events(self):
        eid = self.db.add_event(iso_now(), "+919876543210", 87, "HIGH_RISK", "BLOCK", "test")
        self.assertGreater(eid, 0)
        rows = self.db.recent_events(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["number"], "+919876543210")
        self.assertEqual(self.db.count_events_for_number("+919876543210"), 1)

    def test_settings(self):
        self.db.set_setting("foo", "bar")
        self.assertEqual(self.db.get_setting("foo"), "bar")
        self.db.set_setting("foo", "baz")
        self.assertEqual(self.db.get_setting("foo"), "baz")
        self.assertIsNone(self.db.get_setting("missing"))

    def test_sql_injection_resistance(self):
        n = "+919876543210'); DROP TABLE numbers;--"
        try:
            self.db.upsert_list_entry(n, "blacklist", None, iso_now())
        except Exception:
            pass
        cur = self.db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='numbers'"
        )
        self.assertIsNotNone(cur.fetchone())


if __name__ == "__main__":
    unittest.main()
