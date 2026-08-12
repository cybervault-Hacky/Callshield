"""Phase 8.5.2 Universal Number Intelligence tests."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from callshield.database import Database
from callshield.universal import (
    ContactImportError,
    ContactStore,
    UniversalNumberEngine,
    parse_contact_file,
)
from callshield.universal.engine import detect_country
from callshield.utils import mask_number
from tests._common import IsolatedEnv, run_cli
from tests._ui import caps, emoji_characters, make_app, plain, render


class UniversalCase(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()


class TestValidInvalidUnknown(UniversalCase):
    def test_valid_number(self):
        db = Database(self.cfg.database_path)
        try:
            profile = UniversalNumberEngine(db, self.cfg).profile("+919876543210")
            self.assertTrue(profile.valid)
            self.assertEqual(profile.normalized_number.value, "+919876543210")
            self.assertEqual(profile.masked_number.value, mask_number("+919876543210"))
            self.assertNotEqual(profile.masked_number.value, "+919876543210")
        finally:
            db.close()

    def test_invalid_number(self):
        db = Database(self.cfg.database_path)
        try:
            profile = UniversalNumberEngine(db, self.cfg).profile("not-a-number")
            self.assertFalse(profile.valid)
            self.assertEqual(profile.age.value, "NOT AVAILABLE")
            self.assertEqual(profile.owner_identity.value, "NOT VERIFIED")
        finally:
            db.close()

    def test_unknown_number_has_no_identity(self):
        db = Database(self.cfg.database_path)
        try:
            profile = UniversalNumberEngine(db, self.cfg).profile("+15551234567")
            self.assertEqual(profile.contact_name.value, "NOT AVAILABLE")
            self.assertEqual(profile.age.value, "NOT AVAILABLE")
            self.assertEqual(profile.owner_identity.value, "NOT VERIFIED")
            self.assertEqual(profile.local_contact_status.value, "NOT SAVED")
        finally:
            db.close()


class TestLocalContacts(UniversalCase):
    def test_local_contact_match_and_no_match(self):
        db = Database(self.cfg.database_path)
        try:
            store = ContactStore(db, self.cfg)
            store.upsert("+919876543210", "Ada")
            engine = UniversalNumberEngine(db, self.cfg)
            hit = engine.profile("+919876543210")
            miss = engine.profile("+919876500000")
            self.assertEqual(hit.contact_name.value, "Ada")
            self.assertEqual(hit.local_contact_status.value, "SAVED")
            self.assertEqual(hit.contact_source.value, "Local Contacts")
            self.assertEqual(hit.owner_identity.value, "NOT VERIFIED")
            self.assertEqual(miss.contact_name.value, "NOT AVAILABLE")
            self.assertEqual(miss.local_contact_status.value, "NOT SAVED")
        finally:
            db.close()

    def test_duplicate_contacts_update(self):
        db = Database(self.cfg.database_path)
        try:
            store = ContactStore(db, self.cfg)
            self.assertEqual(store.upsert("+919876543210", "One"), "inserted")
            self.assertEqual(store.upsert("+919876543210", "Two"), "updated")
            self.assertEqual(store.count(), 1)
            self.assertEqual(store.lookup("+919876543210").display_name, "Two")
        finally:
            db.close()

    def test_normalization_on_import(self):
        db = Database(self.cfg.database_path)
        try:
            store = ContactStore(db, self.cfg)
            summary = store.import_pairs(
                [("09876543210", "Local"), ("+91 98765 43210", "Dup")],
                self.cfg.default_country,
            )
            self.assertEqual(store.count(), 1)
            self.assertGreaterEqual(summary["accepted"] + summary["skipped"], 1)
        finally:
            db.close()


class TestIdentitySemantics(UniversalCase):
    def test_no_fabricated_age_or_identity(self):
        db = Database(self.cfg.database_path)
        try:
            profile = UniversalNumberEngine(db, self.cfg).profile("+919111111111")
            public = profile.to_public_dict()
            self.assertEqual(public["age"]["value"], "NOT AVAILABLE")
            self.assertEqual(public["age"]["availability"], "NOT_AVAILABLE")
            self.assertEqual(public["owner_identity"]["availability"], "NOT_VERIFIED")
            blob = json.dumps(public)
            self.assertNotIn("years old", blob.lower())
            self.assertNotIn("occupation", blob.lower())
        finally:
            db.close()

    def test_unavailable_data_is_labelled(self):
        db = Database(self.cfg.database_path)
        try:
            profile = UniversalNumberEngine(db, self.cfg).profile("+819012345678")
            self.assertEqual(profile.region.availability, "NOT_AVAILABLE")
        finally:
            db.close()


class TestReputationIntegration(UniversalCase):
    def test_reputation_and_trend_fields(self):
        run_cli(self.cfg, "scan", "+919876543299")
        db = Database(self.cfg.database_path)
        try:
            profile = UniversalNumberEngine(db, self.cfg).profile("+919876543299")
            self.assertEqual(profile.reputation_score.availability, "AVAILABLE")
            self.assertIsInstance(profile.reputation_score.value, int)
            self.assertIn(profile.behavioral_trend.availability, ("AVAILABLE", "UNKNOWN"))
        finally:
            db.close()


class TestPrivacyStorage(UniversalCase):
    def test_contacts_store_hash_and_mask_not_plaintext(self):
        number = "+919876543210"
        db = Database(self.cfg.database_path)
        try:
            ContactStore(db, self.cfg).upsert(number, "Ada")
            row = db._conn.execute("SELECT * FROM local_contacts").fetchone()
            values = str(tuple(row))
            self.assertNotIn(number, values)
            self.assertNotEqual(row["number_masked"], number)
            self.assertEqual(row["display_name"], "Ada")
        finally:
            db.close()


class TestContactImportFormats(UniversalCase):
    def test_csv_and_json_import(self):
        csv_path = self.env.root / "contacts.csv"
        csv_path.write_text("name,number\nAda,+919876543210\nBob,bad\n", encoding="utf-8")
        json_path = self.env.root / "contacts.json"
        json_path.write_text(
            json.dumps([{"name": "Cara", "number": "+919876543211"}]),
            encoding="utf-8",
        )
        code, out = run_cli(self.cfg, "contacts", "import", str(csv_path))
        self.assertEqual(code, 0)
        self.assertIn("Accepted", out)
        code, out = run_cli(self.cfg, "contacts", "import", str(json_path))
        self.assertEqual(code, 0)
        code, out = run_cli(self.cfg, "contacts", "status")
        self.assertIn("2", out)
        code, out = run_cli(self.cfg, "contacts", "list")
        self.assertNotIn("+919876543210", out)
        self.assertIn("Ada", out)

    def test_malformed_import(self):
        bad = self.env.root / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        code, out = run_cli(self.cfg, "contacts", "import", str(bad))
        self.assertNotEqual(code, 0)

    def test_oversized_import(self):
        huge = self.env.root / "huge.csv"
        huge.write_bytes(b"x" * (1024 * 1024 + 10))
        code, _out = run_cli(self.cfg, "contacts", "import", str(huge))
        self.assertNotEqual(code, 0)

    def test_bounded_import_limit(self):
        path = self.env.root / "many.json"
        rows = [{"name": "N%d" % i, "number": "+9198765%05d" % i} for i in range(5001)]
        path.write_text(json.dumps(rows), encoding="utf-8")
        with self.assertRaises(ContactImportError):
            parse_contact_file(path)

    def test_remove_and_clear(self):
        db = Database(self.cfg.database_path)
        try:
            store = ContactStore(db, self.cfg)
            store.upsert("+919876543210", "Ada")
            self.assertTrue(store.remove("+919876543210"))
            store.upsert("+919876543211", "Bob")
            self.assertEqual(store.clear(), 1)
        finally:
            db.close()


class TestCLINumber(UniversalCase):
    def test_number_command_and_json(self):
        code, out = run_cli(self.cfg, "number", "+919876543210")
        self.assertEqual(code, 0)
        self.assertIn("NUMBER INTELLIGENCE", out)
        self.assertIn("NOT AVAILABLE", out)
        self.assertIn("NOT VERIFIED", out)
        self.assertNotIn("+919876543210", out)
        code, out = run_cli(self.cfg, "number", "+919876543210", "--json")
        payload = json.loads(out)
        self.assertEqual(payload["age"]["value"], "NOT AVAILABLE")
        self.assertEqual(payload["owner_identity"]["availability"], "NOT_VERIFIED")
        self.assertNotIn("+919876543210", out)

    def test_invalid_number_exit(self):
        code, _out = run_cli(self.cfg, "number", "xx")
        self.assertEqual(code, 3)

    def test_scan_remains_compatible(self):
        code, out = run_cli(self.cfg, "scan", "+919876543210")
        self.assertEqual(code, 0)
        self.assertIn("ANALYSIS", out)

    def test_contacts_scan_json(self):
        csv_path = self.env.root / "one.csv"
        csv_path.write_text("name,number\nAda,+919876543210\n", encoding="utf-8")
        run_cli(self.cfg, "contacts", "import", str(csv_path))
        code, out = run_cli(self.cfg, "contacts", "scan", "--json")
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["known_contacts"], 1)


class TestTUI(UniversalCase):
    def test_screen_renders(self):
        ctx, app, text = None, None, None
        ctx, app = make_app(self.cfg, screen_key="number_intel",
                            caps=caps(width=100, height=70))
        text = render(app)
        self.assertIn(ctx.t("number_intel.title"), text)
        for key in ("number_intel.scan", "number_intel.saved", "number_intel.imported",
                    "number_intel.history", "number_intel.compare", "number_intel.export"):
            self.assertIn(ctx.t(key), text)

    def test_number_scan_cards(self):
        ctx, app = make_app(
            self.cfg,
            screen_key="number_intel",
            answers=["+919876543210"],
            caps=caps(width=100, height=80),
        )
        app.handle_key("1")
        text = render(app)
        self.assertIn("IDENTITY", text)
        self.assertIn("THREAT", text)
        self.assertIn("REPUTATION", text)
        self.assertIn("EVIDENCE", text)
        self.assertIn("PRIVACY", text)
        self.assertIn("NOT VERIFIED", text)
        self.assertNotIn("+919876543210", text)

    def test_narrow_terminal(self):
        ctx, app = make_app(self.cfg, screen_key="number_intel",
                            caps=caps(width=40, height=30))
        for line in plain(app.render()).split("\n"):
            self.assertLessEqual(len(line), 40)

    def test_cjk_hindi_hinglish_render(self):
        ctx, app = make_app(self.cfg, screen_key="number_intel")
        for code in ("hi", "hinglish", "ja", "zh"):
            ctx.set_preference("language", code)
            app.current.rebuild()
            lines = app.current.body(ctx.surface)
            self.assertTrue(all(isinstance(line, str) for line in lines))

    def test_all_nine_languages(self):
        from callshield.ui.i18n.catalog import LANGUAGES

        ctx, _app = make_app(self.cfg)
        for code in LANGUAGES:
            ctx.set_preference("language", code)
            screen = ctx.make_screen("number_intel")
            screen.on_enter()
            lines = screen.body(ctx.surface)
            self.assertTrue(lines)
            self.assertEqual(emoji_characters("\n".join(lines)), [])


class TestNoNetwork(UniversalCase):
    def test_universal_module_has_no_network(self):
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "callshield/universal"
        forbidden = {"socket", "http", "urllib", "requests", "aiohttp"}
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name.split(".")[0] for alias in node.names]
                    if getattr(node, "module", None):
                        names.append(node.module.split(".")[0])
                    self.assertTrue(forbidden.isdisjoint(names), path)

    def test_country_detection_is_local(self):
        self.assertEqual(detect_country("919876543210", None), "IN")
        self.assertIsNone(detect_country("999999", None))


if __name__ == "__main__":
    unittest.main()
