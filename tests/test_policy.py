"""Phase 5 policy engine, emergency switch, and simulation tests."""

import os
import unittest
from pathlib import Path
from unittest import mock

from callshield.config import Config
from callshield.policy import (
    DEFAULT_POLICIES,
    PolicyEngine,
    enable_emergency_off,
    is_emergency_off,
    reset_emergency_off,
    thresholds_for_config,
)
from tests._common import IsolatedEnv, run_cli


def detection(risk=0, confidence=0, verdict="UNKNOWN", whitelisted=False):
    return {
        "risk_score": risk,
        "confidence": confidence,
        "verdict": verdict,
        "reputation": "TRUSTED" if whitelisted else "UNKNOWN",
        "reason": "User whitelist" if whitelisted else "test",
        "signals": [{"name": "whitelist_match"}] if whitelisted else [],
    }


class TestPolicyEngine(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.engine = PolicyEngine(self.cfg)

    def tearDown(self):
        self.env.stop()

    def decide(self, value, **overrides):
        defaults = {
            "mode": "ACTIVE",
            "screening_enabled": True,
            "active_confirmed": True,
            "emergency_off": False,
        }
        defaults.update(overrides)
        return self.engine.decide(value, **defaults)

    def test_safe_unknown_and_suspicious_allow(self):
        for value in (
            detection(5, 90, "SAFE"),
            detection(0, 0, "UNKNOWN"),
            detection(60, 95, "SUSPICIOUS"),
        ):
            with self.subTest(value=value):
                decision = self.decide(value)
                self.assertEqual(decision.recommended_action, "ALLOW")
                self.assertEqual(decision.applied_action, "ALLOW")

    def test_high_risk_high_confidence_active_blocks(self):
        decision = self.decide(detection(90, 90, "MALICIOUS"))
        self.assertEqual(decision.recommended_action, "BLOCK")
        self.assertEqual(decision.applied_action, "BLOCK")
        self.assertEqual(decision.reason, "ACTIVE_POLICY_BLOCK")

    def test_high_risk_low_confidence_active_allows(self):
        decision = self.decide(detection(95, 70, "HIGH_RISK"))
        self.assertEqual(decision.recommended_action, "ALLOW")
        self.assertEqual(decision.applied_action, "ALLOW")

    def test_high_risk_dry_run_recommends_block_applies_allow(self):
        decision = self.decide(
            detection(95, 95, "MALICIOUS"),
            mode="DRY_RUN",
            active_confirmed=False,
        )
        self.assertEqual(decision.recommended_action, "BLOCK")
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "DRY_RUN")

    def test_whitelist_always_wins(self):
        decision = self.decide(detection(100, 100, "MALICIOUS", whitelisted=True))
        self.assertEqual(decision.recommended_action, "ALLOW")
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "WHITELIST_OVERRIDE")

    def test_emergency_off_overrides_active_block(self):
        decision = self.decide(
            detection(100, 100, "MALICIOUS"), emergency_off=True
        )
        self.assertEqual(decision.recommended_action, "BLOCK")
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "EMERGENCY_OFF")

    def test_disabled_active_never_applies_block(self):
        decision = self.decide(
            detection(100, 100, "MALICIOUS"), screening_enabled=False
        )
        self.assertEqual(decision.recommended_action, "BLOCK")
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertEqual(decision.reason, "SCREENING_DISABLED")

    def test_invalid_threshold_fails_open(self):
        self.cfg.balanced_active_block_threshold = 101
        decision = self.decide(detection(100, 100, "MALICIOUS"))
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertTrue(decision.policy_error)
        self.assertEqual(decision.reason, "INVALID_POLICY_CONFIG")

    def test_invalid_policy_fails_open(self):
        decision = self.decide(
            detection(100, 100, "MALICIOUS"), policy_name="INVALID"
        )
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertTrue(decision.policy_error)

    def test_invalid_mode_fails_open(self):
        decision = self.decide(
            detection(100, 100, "MALICIOUS"), mode="UNEXPECTED"
        )
        self.assertEqual(decision.applied_action, "ALLOW")
        self.assertTrue(decision.policy_error)

    def test_default_policy_thresholds(self):
        for name, expected in DEFAULT_POLICIES.items():
            with self.subTest(name=name):
                actual = thresholds_for_config(self.cfg, name)
                self.assertEqual(actual, expected)

    def test_configurable_thresholds(self):
        self.cfg.strict_active_block_threshold = 70
        self.cfg.strict_confidence_threshold = 65
        decision = self.decide(
            detection(72, 66, "HIGH_RISK"), policy_name="STRICT"
        )
        self.assertEqual(decision.applied_action, "BLOCK")
        self.assertEqual(decision.threshold, 70)
        self.assertEqual(decision.confidence_threshold, 65)


class TestEmergencySwitch(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        self.path = Path(self.cfg.emergency_off_file)

    def tearDown(self):
        self.env.stop()

    def test_enable_and_reset_are_idempotent_and_owner_only(self):
        self.assertTrue(enable_emergency_off(self.cfg))
        self.assertFalse(enable_emergency_off(self.cfg))
        self.assertTrue(is_emergency_off(self.cfg))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(reset_emergency_off(self.cfg))
        self.assertFalse(reset_emergency_off(self.cfg))
        self.assertFalse(is_emergency_off(self.cfg))

    def test_unsafe_emergency_path_fails_closed_to_allow(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.mkdir()
        self.assertTrue(is_emergency_off(self.cfg))


class TestPolicyCLI(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()

    def tearDown(self):
        self.env.stop()

    def test_active_requires_explicit_confirmation(self):
        with mock.patch("builtins.input", return_value=""):
            code, output = run_cli(self.cfg, "screening", "mode", "active")
        self.assertEqual(code, 0)
        self.assertIn("was not enabled", output)
        self.assertFalse(self.cfg.screening_enabled)
        self.assertEqual(self.cfg.screening_mode, "DRY_RUN")

    def test_active_confirmation_enables_protection(self):
        with mock.patch("builtins.input", return_value="yes"):
            code, output = run_cli(self.cfg, "screening", "mode", "active")
        self.assertEqual(code, 0)
        self.assertIn("ACTIVE PROTECTION", output)
        self.assertTrue(self.cfg.screening_enabled)
        self.assertTrue(self.cfg.active_mode_confirmed)
        self.assertEqual(self.cfg.screening_mode, "ACTIVE")

    def test_policy_display_and_selection(self):
        code, output = run_cli(self.cfg, "screening", "policy")
        self.assertEqual(code, 0)
        for name in ("RELAXED", "BALANCED", "STRICT"):
            self.assertIn(name, output)
        code, output = run_cli(self.cfg, "screening", "policy", "strict")
        self.assertEqual(code, 0)
        self.assertEqual(self.cfg.screening_policy, "STRICT")
        self.assertIn("(CURRENT)", output)

    def test_policy_simulation_never_touches_real_calls(self):
        code, output = run_cli(
            self.cfg,
            "policy",
            "test",
            "--risk",
            "95",
            "--confidence",
            "95",
            "--mode",
            "active",
        )
        self.assertEqual(code, 0)
        self.assertIn("SIMULATION ONLY", output)
        self.assertIn("Recommended:         BLOCK", output)
        self.assertIn("Applied:             BLOCK", output)

    def test_policy_simulation_whitelist_and_emergency_allow(self):
        for extra in (("--whitelist",), ("--emergency-off",)):
            code, output = run_cli(
                self.cfg,
                "policy",
                "test",
                "--risk",
                "100",
                "--confidence",
                "100",
                "--mode",
                "active",
                *extra,
            )
            self.assertEqual(code, 0)
            self.assertIn("Applied:             ALLOW", output)

    def test_emergency_commands_do_not_resume_active(self):
        self.cfg.screening_enabled = True
        self.cfg.screening_mode = "ACTIVE"
        self.cfg.active_mode_confirmed = True
        code, _ = run_cli(self.cfg, "emergency-off")
        self.assertEqual(code, 0)
        self.assertFalse(self.cfg.screening_enabled)
        self.assertEqual(self.cfg.screening_mode, "DRY_RUN")
        code, output = run_cli(self.cfg, "emergency-reset")
        self.assertEqual(code, 0)
        self.assertIn("was not enabled", output)
        self.assertFalse(self.cfg.screening_enabled)
        self.assertEqual(self.cfg.screening_mode, "DRY_RUN")


if __name__ == "__main__":
    unittest.main()
