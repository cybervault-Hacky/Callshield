"""Phase 8 adaptive trend, volatility, and delta tests."""

import unittest

from callshield.adaptive.trends import (
    NOISE_THRESHOLD,
    SUDDEN_CHANGE_THRESHOLD,
    analyze_trend,
)


class TestAdaptiveTrends(unittest.TestCase):
    def test_insufficient_data(self):
        result = analyze_trend(
            [20, 30], [40, 45],
            baseline_score=20,
            baseline_confidence=40,
            current_score=30,
            current_confidence=45,
        )
        self.assertEqual(result.trend, "INSUFFICIENT_DATA")

    def test_sustained_worsening(self):
        result = analyze_trend(
            [20, 35, 55], [40, 50, 60],
            baseline_score=20,
            baseline_confidence=40,
            current_score=55,
            current_confidence=60,
        )
        self.assertEqual(result.trend, "WORSENING")
        self.assertEqual(result.risk_delta, 35)

    def test_sustained_improving(self):
        result = analyze_trend(
            [90, 70, 45], [80, 75, 70],
            baseline_score=90,
            baseline_confidence=80,
            current_score=45,
            current_confidence=70,
        )
        self.assertEqual(result.trend, "IMPROVING")
        self.assertEqual(result.risk_delta, -45)

    def test_tiny_noise_is_stable(self):
        result = analyze_trend(
            [50, 52, 49, 51], [60, 61, 60, 62],
            baseline_score=50,
            baseline_confidence=60,
            current_score=51,
            current_confidence=62,
        )
        self.assertEqual(result.trend, "STABLE")
        self.assertLess(abs(result.risk_delta), NOISE_THRESHOLD)

    def test_repeated_oscillation_is_volatile(self):
        result = analyze_trend(
            [20, 80, 25, 75, 30], [50, 80, 45, 75, 40],
            baseline_score=20,
            baseline_confidence=50,
            current_score=30,
            current_confidence=40,
        )
        self.assertEqual(result.trend, "VOLATILE")
        self.assertGreaterEqual(result.direction_changes, 2)

    def test_sudden_change_is_explicit(self):
        result = analyze_trend(
            [10, 12, 50], [40, 40, 60],
            baseline_score=10,
            baseline_confidence=40,
            current_score=50,
            current_confidence=60,
        )
        self.assertTrue(result.sudden_change)
        self.assertGreaterEqual(SUDDEN_CHANGE_THRESHOLD, 20)

    def test_confidence_delta_is_separate(self):
        result = analyze_trend(
            [40, 50, 60], [20, 30, 70],
            baseline_score=40,
            baseline_confidence=20,
            current_score=60,
            current_confidence=70,
        )
        self.assertEqual(result.risk_delta, 20)
        self.assertEqual(result.confidence_delta, 50)


if __name__ == "__main__":
    unittest.main()
