"""Phase 8 adaptive context safety in the existing policy engine."""

import unittest

from callshield.policy import PolicyEngine
from tests._common import IsolatedEnv


class TestIntelligencePolicy(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(
            screening_enabled=True,
            screening_mode="ACTIVE",
            active_mode_confirmed=True,
        )
        self.engine = PolicyEngine(self.cfg)

    def tearDown(self):
        self.env.stop()

    def detection(self, risk=95, confidence=95, context=None):
        return {
            "risk_score": risk,
            "confidence": confidence,
            "verdict": "MALICIOUS",
            "signals": [],
            "reputation": "MALICIOUS",
            "reputation_profile": {"available": True, "trusted": False},
            "intelligence_context": context
            or {
                "available": True,
                "behavioral_trend": "STABLE",
                "trust_state": "UNTRUSTED",
            },
        }

    def test_intelligence_unavailable_fails_open(self):
        value = self.detection(
            context={"available": False, "behavioral_trend": "INSUFFICIENT_DATA"}
        )
        decision = self.engine.decide(value, emergency_off=False)
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "INTELLIGENCE_UNAVAILABLE")

    def test_volatile_context_can_only_make_block_safer(self):
        value = self.detection(
            context={
                "available": True,
                "behavioral_trend": "VOLATILE",
                "trust_state": "UNTRUSTED",
            }
        )
        decision = self.engine.decide(value, emergency_off=False)
        self.assertEqual(decision.recommended_action, "BLOCK")
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "VOLATILE_INTELLIGENCE_REVIEW")

    def test_worsening_trend_alone_cannot_raise_risk_to_block(self):
        value = self.detection(
            risk=50,
            confidence=100,
            context={
                "available": True,
                "behavioral_trend": "WORSENING",
                "current_score": 100,
                "trust_state": "UNTRUSTED",
            },
        )
        decision = self.engine.decide(value, emergency_off=False)
        self.assertEqual(decision.recommended_action, "ALLOW")
        self.assertEqual(decision.applied_action, "ALLOW")

    def test_intelligence_trust_state_is_allow_override(self):
        value = self.detection(
            context={
                "available": True,
                "behavioral_trend": "WORSENING",
                "trust_state": "TRUSTED",
            }
        )
        decision = self.engine.decide(value, emergency_off=False)
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "WHITELIST_OVERRIDE")

    def test_emergency_remains_absolute(self):
        decision = self.engine.decide(self.detection(), emergency_off=True)
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "EMERGENCY_OFF")

    def test_dry_run_remains_recommendation_only(self):
        decision = self.engine.decide(
            self.detection(),
            mode="DRY_RUN",
            active_confirmed=False,
            emergency_off=False,
        )
        self.assertEqual(decision.recommended_action, "BLOCK")
        self.assertEqual(decision.applied_action, "ALLOW")

    def test_active_stable_context_preserves_existing_policy(self):
        decision = self.engine.decide(self.detection(), emergency_off=False)
        self.assertEqual(decision.recommended_action, "BLOCK")
        self.assertEqual(decision.applied_action, "BLOCK")


if __name__ == "__main__":
    unittest.main()
