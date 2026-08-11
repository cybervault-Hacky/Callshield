"""Phase 8 deterministic intelligence snapshot and explanation tests."""

import json
import unittest
from unittest import mock

from callshield.adaptive import BehaviorEngine
from callshield.database import Database
from tests._adaptive import observation, reputation
from tests._common import IsolatedEnv


class TestIntelligenceSnapshot(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.db = Database(self.cfg.database_path)
        self.engine = BehaviorEngine(self.db, self.cfg)
        self.number = "+919876543210"

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def test_snapshot_contains_required_fields(self):
        value = self.engine.snapshot(
            self.number,
            reputation=reputation(self.number, score=70, confidence=75),
            detection={"recommended_action": "BLOCK"},
            observation=observation(1, 70, 75, recommended="BLOCK"),
        )
        public = value.to_public_dict(include_history=True)
        for key in (
            "reputation_score",
            "reputation_confidence",
            "behavioral_trend",
            "patterns",
            "recent_observation_count",
            "recent_high_risk_count",
            "recent_block_recommendations",
            "recent_user_reports",
            "trust_state",
            "risk_delta",
            "confidence_delta",
            "baseline_score",
            "current_score",
            "explanations",
            "history",
        ):
            self.assertIn(key, public)
        json.dumps(public)

    def test_risk_and_confidence_delta_use_previous_baseline(self):
        self.engine.snapshot(
            self.number,
            reputation=reputation(self.number, score=40, confidence=30),
            observation=observation(1, 40, 30),
        )
        value = self.engine.snapshot(
            self.number,
            reputation=reputation(self.number, score=70, confidence=65),
            observation=observation(2, 70, 65),
        )
        self.assertEqual(value.baseline_score, 40)
        self.assertEqual(value.current_score, 70)
        self.assertEqual(value.risk_delta, 30)
        self.assertEqual(value.confidence_delta, 35)

    def test_observed_recommended_applied_confirmed_are_distinct(self):
        item = observation(
            3,
            90,
            90,
            recommended="BLOCK",
            applied="BLOCK",
            event_type="INCOMING_CALL",
        )
        value = self.engine.snapshot(
            self.number,
            reputation=reputation(self.number, score=90, confidence=90),
            detection={"recommended_action": "BLOCK"},
            observation=item,
        )
        self.assertEqual(value.observed, "INCOMING_CALL")
        self.assertEqual(value.recommended, "BLOCK")
        self.assertEqual(value.applied, "BLOCK")
        self.assertFalse(value.confirmed)

    def test_explanations_match_patterns_and_deltas(self):
        for index, score in enumerate((20, 50, 80), 1):
            value = self.engine.snapshot(
                self.number,
                reputation=reputation(self.number, score=score, confidence=80),
                observation=observation(index, score, 80, recommended="BLOCK"),
            )
        explanations = {pattern.explanation for pattern in value.patterns}
        self.assertTrue(explanations.issubset(set(value.explanations)))
        self.assertTrue(any("Risk increased" in item for item in value.explanations))

    def test_corrupt_storage_fails_open(self):
        with mock.patch.object(
            self.engine.storage, "timeline", side_effect=RuntimeError("corrupt")
        ):
            value = self.engine.snapshot(
                self.number,
                reputation=reputation(self.number, score=100, confidence=100),
            )
        self.assertFalse(value.available)
        self.assertEqual(value.recommended, "ALLOW")
        self.assertEqual(value.applied, "ALLOW")
        self.assertEqual(value.behavioral_trend, "INSUFFICIENT_DATA")

    def test_repeated_snapshot_is_deterministic_without_new_observation(self):
        rep = reputation(self.number, score=55, confidence=60)
        first = self.engine.snapshot(self.number, reputation=rep, persist=False)
        second = self.engine.snapshot(self.number, reputation=rep, persist=False)
        self.assertEqual(first.to_public_dict(), second.to_public_dict())


if __name__ == "__main__":
    unittest.main()
