"""Automated subset of the documented Phase 6 static security audit."""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestSecurityAudit(unittest.TestCase):
    def test_python_has_no_forbidden_execution_or_deserialization(self):
        violations = []
        for path in (ROOT / "callshield").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in {
                        "eval",
                        "exec",
                    }:
                        violations.append((path, node.lineno, node.func.id))
                    if isinstance(node.func, ast.Attribute):
                        owner = node.func.value
                        if (
                            isinstance(owner, ast.Name)
                            and owner.id == "os"
                            and node.func.attr == "system"
                        ):
                            violations.append((path, node.lineno, "os.system"))
                        if (
                            isinstance(owner, ast.Name)
                            and owner.id == "pickle"
                        ):
                            violations.append((path, node.lineno, "pickle"))
                    for keyword in node.keywords:
                        if (
                            keyword.arg == "shell"
                            and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value is True
                        ):
                            violations.append((path, node.lineno, "shell=True"))
                if isinstance(node, ast.Attribute) and node.attr == "AF_INET":
                    violations.append((path, node.lineno, "AF_INET"))
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [alias.name for alias in node.names]
                    if "pickle" in names:
                        violations.append((path, node.lineno, "pickle import"))
        self.assertEqual(violations, [])

    def test_android_has_no_process_execution_or_network_socket(self):
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "android/app/src/main/java").rglob("*.kt")
        )
        for forbidden in (
            "Runtime.exec",
            "ProcessBuilder",
            "java.net.Socket",
            "ServerSocket",
        ):
            self.assertNotIn(forbidden, combined)
        self.assertIn("LocalSocket", combined)

    def test_manifest_has_no_dangerous_permissions(self):
        manifest = (ROOT / "android/app/src/main/AndroidManifest.xml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("<uses-permission", manifest)
        for permission in (
            "INTERNET",
            "CAMERA",
            "RECORD_AUDIO",
            "READ_CONTACTS",
            "ACCESS_FINE_LOCATION",
            "BIND_ACCESSIBILITY_SERVICE",
        ):
            self.assertNotIn(permission, manifest)

    def test_readme_is_the_project_documentation(self):
        self.assertTrue((ROOT / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
