import unittest

from callshield.reputation import ReputationSignals
from callshield.scoring import compute_score, verdict_for


def _sig(**kw):
    s = ReputationSignals()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class TestScoring(unittest.TestCase):
    def test_unknown_zero(self):
        brk = compute_score(_sig())
        self.assertEqual(brk.score, 0)
        self.assertEqual(brk.level, "LOW")

    def test_minimum_clamp(self):
        brk = compute_score(_sig(in_whitelist=True))
        self.assertEqual(brk.score, 0)

    def test_maximum_clamp(self):
        brk = compute_score(_sig(
            in_blacklist=True,
            stored_reputation="CRITICAL",
            previous_suspicious=100,
        ))
        # Whitelist not set; blacklist + other sigs can't exceed 100
        self.assertLessEqual(brk.score, 100)

    def test_blacklist_score_is_high(self):
        brk = compute_score(_sig(in_blacklist=True))
        self.assertGreaterEqual(brk.score, 80)
        self.assertEqual(brk.level, "CRITICAL")

    def test_whitelist_overrides_blacklist(self):
        brk = compute_score(_sig(in_whitelist=True, in_blacklist=True))
        self.assertEqual(brk.score, 0)
        self.assertTrue(any("conflict" in label.lower() for label, *_ in brk.signals))

    def test_previous_suspicious_adds_small_delta(self):
        brk = compute_score(_sig(previous_suspicious=2))
        # 2 events * 5 = +10
        self.assertGreaterEqual(brk.score, 10)

    def test_verdict_block_for_blacklist(self):
        brk = compute_score(_sig(in_blacklist=True))
        v, action, _ = verdict_for(brk, _sig(in_blacklist=True), threshold=60)
        self.assertEqual(v, "HIGH_RISK")
        self.assertEqual(action, "BLOCK")

    def test_verdict_allow_for_whitelist(self):
        brk = compute_score(_sig(in_whitelist=True))
        v, action, reason = verdict_for(brk, _sig(in_whitelist=True), threshold=60)
        self.assertEqual(v, "SAFE")
        self.assertEqual(action, "ALLOW")
        self.assertIn("whitelist", reason.lower())

    def test_verdict_unknown_when_clean(self):
        brk = compute_score(_sig())
        v, action, _ = verdict_for(brk, _sig(), threshold=60)
        self.assertEqual(v, "UNKNOWN")
        self.assertEqual(action, "ALLOW")


if __name__ == "__main__":
    unittest.main()
