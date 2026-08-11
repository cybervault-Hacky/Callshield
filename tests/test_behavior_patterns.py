"""Phase 8 explainable measured behavioral pattern tests."""

import unittest
from datetime import datetime, timedelta, timezone

from callshield.adaptive.models import TrendResult
from callshield.adaptive.patterns import detect_patterns
from tests._adaptive import observation, reputation


class TestBehaviorPatterns(unittest.TestCase):
    def patterns(self, observations, **values):
        defaults = {
            "reputation": reputation("+919876543210", allowed=0, blocks=0),
            "trend": TrendResult("STABLE", 50, 50, 0, 0, False, 0),
            "recent_reports": 0,
            "trusted": False,
            "trust_expiry": None,
            "now": datetime.now(timezone.utc),
        }
        defaults.update(values)
        return detect_patterns(observations, **defaults)

    def ids(self, values):
        return {item.pattern_id for item in values}

    def test_repeated_high_risk_and_blocks(self):
        values = [
            observation(index, 80, recommended="BLOCK") for index in range(1, 5)
        ]
        patterns = self.patterns(values)
        self.assertIn("repeated_high_risk", self.ids(patterns))
        self.assertIn("repeated_block_recommendation", self.ids(patterns))

    def test_previous_single_block_is_measured(self):
        patterns = self.patterns([observation(1, 70, recommended="BLOCK")])
        self.assertIn("previously_block_recommended", self.ids(patterns))

    def test_repeated_reports(self):
        patterns = self.patterns([], recent_reports=3)
        pattern = next(item for item in patterns if item.pattern_id == "repeated_user_reports")
        self.assertEqual(pattern.evidence["user_reports"], 3)
        self.assertEqual(pattern.observation_count, 3)

    def test_increasing_and_improved_patterns(self):
        worsening = TrendResult("WORSENING", 40, 75, 35, 10, True, 0)
        improving = TrendResult("IMPROVING", 80, 45, -35, -5, True, 0)
        values = [observation(index, risk) for index, risk in enumerate((40, 60, 75), 1)]
        self.assertIn(
            "rapidly_increasing_risk",
            self.ids(self.patterns(values, trend=worsening)),
        )
        self.assertIn(
            "recently_improved",
            self.ids(self.patterns(values, trend=improving)),
        )

    def test_historically_trusted_requires_measurement(self):
        profile = reputation("+919876543210", allowed=4, blocks=0)
        patterns = self.patterns([], reputation=profile)
        self.assertIn("historically_trusted", self.ids(patterns))

    def test_expired_trust_pattern(self):
        expiry = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        patterns = self.patterns([], trust_expiry=expiry, trusted=False)
        self.assertIn("trust_expired", self.ids(patterns))

    def test_volatile_pattern(self):
        trend = TrendResult("VOLATILE", 20, 30, 10, 0, True, 3)
        patterns = self.patterns(
            [observation(index, risk) for index, risk in enumerate((20, 80, 25, 75), 1)],
            trend=trend,
        )
        pattern = next(item for item in patterns if item.pattern_id == "inconsistent_behavior")
        self.assertEqual(pattern.evidence["direction_changes"], 3)

    def test_no_unsupported_short_call_pattern(self):
        patterns = self.patterns([observation(index, 80) for index in range(1, 10)])
        self.assertFalse(any("short" in item.pattern_id for item in patterns))
        self.assertFalse(any("short call" in item.explanation.lower() for item in patterns))

    def test_every_pattern_has_required_explanation_fields(self):
        patterns = self.patterns(
            [observation(index, 80, recommended="BLOCK") for index in range(1, 5)],
            recent_reports=2,
        )
        for pattern in patterns:
            self.assertTrue(pattern.pattern_id)
            self.assertIsInstance(pattern.evidence, dict)
            self.assertGreater(pattern.observation_count, 0)
            self.assertGreaterEqual(pattern.time_window_seconds, 0)
            self.assertTrue(0 <= pattern.confidence <= 100)
            self.assertTrue(pattern.explanation)


if __name__ == "__main__":
    unittest.main()
