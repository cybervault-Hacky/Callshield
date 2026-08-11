"""Phase 6 fail-open policy safety under corrupted state."""

import unittest
import uuid
from unittest import mock

from callshield.config import Config
from callshield.daemon.service import DaemonService
from callshield.policy import PolicyEngine
from tests._common import IsolatedEnv


class TestPolicySafety(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config(
            screening_enabled=True,
            screening_mode="ACTIVE",
            active_mode_confirmed=True,
        )

    def tearDown(self):
        self.env.stop()

    def detection(self):
        return {
            "risk_score": 100,
            "confidence": 100,
            "verdict": "MALICIOUS",
            "reputation": "UNKNOWN",
            "signals": [],
        }

    def test_corrupt_activation_state_allows(self):
        decision = PolicyEngine(self.cfg).decide(
            self.detection(), active_confirmed="yes"
        )
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertTrue(decision.policy_error)

    def test_corrupt_scores_cannot_block(self):
        detection = self.detection()
        detection["risk_score"] = "100"
        detection["confidence"] = None
        decision = PolicyEngine(self.cfg).decide(detection)
        self.assertEqual(decision.applied_action, "ALLOW")

    def test_emergency_state_read_error_allows(self):
        with mock.patch("pathlib.Path.lstat", side_effect=OSError("state failure")):
            decision = PolicyEngine(self.cfg).decide(self.detection())
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertTrue(decision.emergency_off)

    def test_final_boundary_invalid_active_state_allows(self):
        service = DaemonService(self.cfg)
        service.cfg.active_mode_confirmed = False
        response = {
            "protocol": "callshield/1",
            "request_id": str(uuid.uuid4()),
            "risk_score": 100,
            "confidence": 100,
            "verdict": "MALICIOUS",
            "recommended_action": "BLOCK",
            "applied_action": "BLOCK",
            "mode": "ACTIVE",
            "reason": "bad state",
            "latency_ms": 1,
            "policy_name": "BALANCED",
            "threshold": 85,
            "confidence_threshold": 80,
            "emergency_off": False,
            "policy_error": False,
        }
        finalized = service._finalize_screening(response, "+919876543210")
        self.assertEqual(finalized["applied_action"], "ALLOW")
        self.assertEqual(finalized["reason"], "SAFETY_FALLBACK")

    def test_unexpected_policy_exception_isolated(self):
        service = DaemonService(self.cfg)
        with mock.patch(
            "callshield.events.processor.PolicyEngine.decide",
            side_effect=RuntimeError("unexpected"),
        ):
            result = service.processor.process(
                __import__("callshield.events", fromlist=["Event"]).Event(
                    event_type="INCOMING_CALL",
                    number="+919876543210",
                    source="android_call_screening",
                )
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["detection"]["applied_action"], "ALLOW")


if __name__ == "__main__":
    unittest.main()
