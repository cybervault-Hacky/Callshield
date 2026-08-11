"""Phase 7 fail-open reputation integration with Phase 5 policy."""

import unittest
from unittest import mock

from callshield.database import Database
from callshield.events import Event
from callshield.events.processor import EventProcessor
from callshield.policy import PolicyEngine, enable_emergency_off
from callshield.reputation import (
    ReputationProfile,
    ReputationStorage,
    number_fingerprint,
)
from tests._common import IsolatedEnv


class TestReputationPolicy(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(
            screening_enabled=True,
            screening_mode="ACTIVE",
            active_mode_confirmed=True,
        )
        self.db = Database(self.cfg.database_path)

    def tearDown(self):
        self.db.close()
        self.env.stop()

    def detection(self, **values):
        result = {
            "risk_score": 100,
            "confidence": 100,
            "verdict": "MALICIOUS",
            "signals": [],
            "reputation": "MALICIOUS",
        }
        result.update(values)
        return result

    def test_trusted_reputation_is_absolute_allow(self):
        decision = PolicyEngine(self.cfg).decide(
            self.detection(
                trusted=True,
                reputation_profile={"available": True, "trusted": True, "score": 0},
            ),
            emergency_off=False,
        )
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "WHITELIST_OVERRIDE")

    def test_reputation_unavailable_fails_open(self):
        decision = PolicyEngine(self.cfg).decide(
            self.detection(
                reputation_error=True,
                reputation_profile={"available": False},
            ),
            emergency_off=False,
        )
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "REPUTATION_UNAVAILABLE")

    def test_reputation_alone_cannot_raise_detector_to_block(self):
        decision = PolicyEngine(self.cfg).decide(
            self.detection(
                risk_score=50,
                confidence=100,
                reputation_profile={
                    "available": True,
                    "trusted": False,
                    "score": 100,
                    "confidence": 100,
                    "trend": "WORSENING",
                },
            ),
            emergency_off=False,
        )
        self.assertEqual(decision.recommended_action, "ALLOW")
        self.assertEqual(decision.applied_action, "ALLOW")

    def test_event_processor_honors_local_trust_in_active_mode(self):
        number = "+919999977771"
        self.db.upsert_list_entry(
            number, "blacklist", "test", "2026-08-11T00:00:00+00:00"
        )
        ReputationStorage(self.db, self.cfg).set_trust(
            number_fingerprint(number), "+919*****7771", expires_at=None
        )
        result = EventProcessor(self.cfg).process(
            Event(
                event_type="INCOMING_CALL",
                number=number,
                source="android_call_screening",
            )
        )
        self.assertEqual(result["policy"]["applied_action"], "ALLOW")
        self.assertTrue(result["reputation_profile"]["trusted"])

    def test_corrupted_reputation_during_event_fails_open(self):
        unavailable = ReputationProfile.unavailable("hash", "+***", "corrupt")
        with mock.patch(
            "callshield.events.processor.ReputationEngine.calculate",
            return_value=unavailable,
        ):
            result = EventProcessor(self.cfg).process(
                Event(
                    event_type="INCOMING_CALL",
                    number="+919999977772",
                    source="android_call_screening",
                )
            )
        self.assertEqual(result["policy"]["applied_action"], "ALLOW")
        self.assertEqual(result["policy"]["reason"], "REPUTATION_UNAVAILABLE")

    def test_emergency_remains_higher_priority(self):
        enable_emergency_off(self.cfg)
        decision = PolicyEngine(self.cfg).decide(
            self.detection(reputation_profile={"available": True, "trusted": False}),
        )
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "EMERGENCY_OFF")


if __name__ == "__main__":
    unittest.main()
