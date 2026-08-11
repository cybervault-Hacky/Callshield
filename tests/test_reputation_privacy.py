"""Phase 7 local-only and privacy boundary tests."""

import ast
import json
import unittest
from pathlib import Path

from callshield.database import Database
from callshield.reputation import ReputationEngine
from tests._common import IsolatedEnv
from tests._reputation import analysis, measured_signal


class TestReputationPrivacy(unittest.TestCase):
    def test_reputation_package_has_no_network_calls(self):
        root = Path(__file__).resolve().parents[1] / "callshield/reputation"
        violations = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name for alias in node.names]
                    for name in names:
                        if name.split(".")[0] in {
                            "socket",
                            "requests",
                            "urllib",
                            "httpx",
                            "dns",
                        }:
                            violations.append((str(path), node.lineno, name))
        self.assertEqual(violations, [])

    def test_public_profile_excludes_hash_and_plaintext(self):
        env = IsolatedEnv().start()
        number = "+919876543210"
        try:
            cfg = env.make_config()
            db = Database(cfg.database_path)
            try:
                profile = ReputationEngine(db, cfg).calculate(
                    number,
                    analysis=analysis(
                        70, 80, [measured_signal(reason="measured")]
                    ),
                )
                value = profile.to_public_dict()
                serialized = json.dumps(value)
                self.assertNotIn("number_hash", value)
                self.assertNotIn(number, serialized)
            finally:
                db.close()
        finally:
            env.stop()

    def test_no_cloud_or_telemetry_fields(self):
        from callshield.reputation.models import ReputationProfile

        fields = ReputationProfile.__dataclass_fields__
        for forbidden in (
            "account",
            "user_id",
            "cloud_id",
            "telemetry",
            "advertising_id",
            "remote_score",
        ):
            self.assertNotIn(forbidden, fields)


if __name__ == "__main__":
    unittest.main()
