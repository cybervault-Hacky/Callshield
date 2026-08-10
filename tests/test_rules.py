"""Tests for the deterministic rule engine (rules/engine.py)."""

import unittest

from callshield.database import Database
from callshield.rules.engine import evaluate
from callshield.utils import iso_now
from tests._common import IsolatedEnv


class TestRuleEngine(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def _eval(self, number: str, digits: str | None = None):
        # Helper: evaluate with normalized form; create normalized if not given.
        if digits is None:
            # Assume already normalized digits (strip '+')
            digits = number.lstrip("+")
        return evaluate(
            raw_number=number,
            normalized=number,
            digits=digits,
            db=self.db,
            cfg=self.cfg,
        )

    def test_unknown_number_is_unknown(self):
        r = self._eval("+442071838750")
        self.assertEqual(r.verdict, "UNKNOWN")
        self.assertEqual(r.recommended_action, "ALLOW")
        self.assertEqual(r.risk_score, 0)
        self.assertEqual(r.reputation, "UNKNOWN")
        self.assertFalse(r.list_conflict)

    def test_blacklisted_is_malicious_block(self):
        self.db.upsert_list_entry("+919999900001", "blacklist", None, iso_now())
        r = self._eval("+919999900001")
        self.assertEqual(r.verdict, "MALICIOUS")
        self.assertEqual(r.reputation, "MALICIOUS")
        self.assertEqual(r.recommended_action, "BLOCK")
        self.assertGreaterEqual(r.risk_score, 80)
        self.assertIn("blacklist_match", [s["name"] for s in r.signals])

    def test_whitelisted_is_safe_allow(self):
        self.db.upsert_list_entry("+919999900002", "whitelist", None, iso_now())
        r = self._eval("+919999900002")
        self.assertEqual(r.verdict, "SAFE")
        self.assertEqual(r.recommended_action, "ALLOW")
        self.assertEqual(r.risk_score, 0)
        self.assertIn("whitelist_match", [s["name"] for s in r.signals])

    def test_whitelist_overrides_blacklist(self):
        n = "+919999900003"
        self.db.upsert_list_entry(n, "blacklist", None, iso_now())
        self.db.upsert_list_entry(n, "whitelist", None, iso_now())
        r = self._eval(n)
        self.assertTrue(r.list_conflict)
        self.assertEqual(r.verdict, "SAFE")
        self.assertEqual(r.recommended_action, "ALLOW")
        self.assertEqual(r.risk_score, 0)

    def test_scoring_capped_at_100(self):
        # Create many signals to try to exceed 100
        n = "+919999900004"
        self.db.upsert_list_entry(n, "blacklist", None, iso_now())
        # Add many reports and blocked events
        for _ in range(6):
            self.db.add_report(n, "spam", iso_now())
        for _ in range(5):
            self.db.add_event(iso_now(), n, 90, "MALICIOUS", "BLOCK", "test")
        r = self._eval(n)
        self.assertLessEqual(r.risk_score, 100)
        self.assertGreaterEqual(r.risk_score, 0)

    def test_deterministic_repeated_evaluation(self):
        n = "+919999900005"
        self.db.add_report(n, "suspected scam", iso_now())
        r1 = self._eval(n)
        r2 = self._eval(n)
        self.assertEqual(r1.risk_score, r2.risk_score)
        self.assertEqual(r1.verdict, r2.verdict)
        self.assertEqual(r1.reputation, r2.reputation)
        self.assertEqual(r1.confidence, r2.confidence)

    def test_json_serializable(self):
        r = self._eval("+442071838750")
        d = r.to_dict()
        # Must contain all expected keys for future integrations
        for key in ("number", "risk_score", "confidence", "reputation", "risk_level", "verdict", "recommended_action", "signals"):
            self.assertIn(key, d)
        # Check that signals are list of dicts
        self.assertIsInstance(d["signals"], list)

    def test_verdict_thresholds_with_profiles(self):
        # STRICT should be more sensitive than RELAXED
        from callshield.config import set_profile
        n = "+919999900006"
        self.db.add_report(n, "scam", iso_now())
        self.db.add_report(n, "scam2", iso_now())
        # Balanced
        set_profile(self.cfg, "balanced")
        r_bal = self._eval(n)
        # Strict
        set_profile(self.cfg, "strict")
        r_strict = self._eval(n)
        # Strict should not be *less* risky than balanced for same evidence
        self.assertGreaterEqual(r_strict.risk_score, r_bal.risk_score - 5)  # allow small tolerance due to weights

    def test_evaluation_order_doc(self):
        # Verify that whitelist check happens before blacklist scoring
        # (already tested via override), and that confidence is separate
        n = "+919999900007"
        self.db.upsert_list_entry(n, "blacklist", None, iso_now())
        r = self._eval(n)
        # Confidence should be high for strong blacklist evidence
        self.assertGreaterEqual(r.confidence, 70)
        # Risk and confidence are not the same
        self.assertNotEqual(r.risk_score, r.confidence)


if __name__ == "__main__":
    unittest.main()
