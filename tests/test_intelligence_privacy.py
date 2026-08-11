"""Phase 8 local-only adaptive intelligence privacy tests."""

import ast
import json
import unittest
from pathlib import Path

from callshield.adaptive import BehaviorEngine
from callshield.database import Database
from tests._adaptive import observation, reputation
from tests._common import IsolatedEnv


class TestIntelligencePrivacy(unittest.TestCase):
    def test_adaptive_package_has_no_network_import(self):
        root = Path(__file__).resolve().parents[1] / "callshield/adaptive"
        violations = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        if alias.name.split(".")[0] in {
                            "socket",
                            "requests",
                            "urllib",
                            "httpx",
                            "dns",
                        }:
                            violations.append((path, node.lineno, alias.name))
        self.assertEqual(violations, [])

    def test_public_snapshot_excludes_hash_and_plaintext(self):
        env = IsolatedEnv().start()
        number = "+919876543210"
        try:
            cfg = env.make_config()
            db = Database(cfg.database_path)
            try:
                value = BehaviorEngine(db, cfg).snapshot(
                    number,
                    reputation=reputation(number, score=70),
                    observation=observation(1, 70),
                ).to_public_dict(include_history=True)
                serialized = json.dumps(value)
                self.assertNotIn("number_hash", value)
                self.assertNotIn(number, serialized)
            finally:
                db.close()
        finally:
            env.stop()

    def test_no_unsupported_telemetry_fields(self):
        from callshield.adaptive.models import BehaviorObservation, IntelligenceSnapshot

        observation_fields = BehaviorObservation.__dataclass_fields__
        snapshot_fields = IntelligenceSnapshot.__dataclass_fields__
        for forbidden in (
            "call_duration",
            "answered_status",
            "caller_identity",
            "location",
            "audio",
            "contacts",
            "device_contents",
        ):
            self.assertNotIn(forbidden, observation_fields)
            self.assertNotIn(forbidden, snapshot_fields)

    def test_new_tables_have_no_plaintext_number(self):
        env = IsolatedEnv().start()
        try:
            cfg = env.make_config()
            db = Database(cfg.database_path)
            try:
                for table in ("intelligence_observations", "intelligence_profiles"):
                    columns = {
                        row[1]
                        for row in db._conn.execute(
                            f"PRAGMA table_info({table})"
                        ).fetchall()
                    }
                    self.assertNotIn("number", columns)
            finally:
                db.close()
        finally:
            env.stop()


if __name__ == "__main__":
    unittest.main()
