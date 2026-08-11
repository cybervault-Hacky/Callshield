"""Phase 7 block-inspection reputation snapshot tests."""

import unittest
import uuid

from callshield.database import Database
from callshield.utils import iso_now
from tests._common import IsolatedEnv, run_cli


class TestReputationBlockInspection(unittest.TestCase):
    def setUp(self):
        self.env = IsolatedEnv().start()
        self.cfg = self.env.make_config()
        db = Database(self.cfg.database_path)
        try:
            self.block_id = db.add_screening_event(
                timestamp=iso_now(),
                number="+919876543210",
                risk_score=95,
                confidence=90,
                verdict="MALICIOUS",
                recommended_action="BLOCK",
                applied_action="BLOCK",
                reason="ACTIVE_POLICY_BLOCK",
                source="android_call_screening",
                event_id=str(uuid.uuid4()),
                mode="ACTIVE",
                policy_action="BLOCK",
                policy_name="BALANCED",
                threshold=85,
                confidence_threshold=80,
                policy_reason="ACTIVE_POLICY_BLOCK",
                reputation_score=88,
                reputation_confidence=72,
                reputation_trend="WORSENING",
                reputation_reasons=["3 historical BLOCK recommendations"],
            )
        finally:
            db.close()

    def tearDown(self):
        self.env.stop()

    def test_block_inspection_includes_reputation_without_plaintext(self):
        code, output = run_cli(
            self.cfg, "blocks", "inspect", str(self.block_id)
        )
        self.assertEqual(code, 0)
        self.assertNotIn("+919876543210", output)
        self.assertIn("Reputation Score:    88", output)
        self.assertIn("Reputation Confidence:", output)
        self.assertIn("Reputation Trend:    WORSENING", output)
        self.assertIn("3 historical BLOCK recommendations", output)


if __name__ == "__main__":
    unittest.main()
