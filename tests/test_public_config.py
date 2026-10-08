"""Regression checks for keeping local profiles out of public templates."""
from pathlib import Path
import tempfile
import unittest
from src.config import _load_yaml
from scripts.check_public_release import inspect_file

class PublicConfigTests(unittest.TestCase):
    def test_missing_private_file_uses_example_and_private_file_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "profile.yaml"
            example = p.with_name("profile.example.yaml")
            example.write_text('name: ""\n', encoding="utf-8")
            self.assertEqual(_load_yaml(p), {"name": ""})
            self.assertFalse(p.exists())
            p.write_text('name: Test User\n', encoding="utf-8")
            self.assertEqual(_load_yaml(p), {"name": "Test User"})
            self.assertEqual(example.read_text(encoding="utf-8"), 'name: ""\n')

    def test_guard_rejects_private_files_and_tokens_without_echoing_value(self):
        self.assertTrue(inspect_file("config/profile.yaml", b"name: test"))
        token = "sk-ant-" + "a" * 40
        findings = inspect_file("sample.py", token.encode())
        self.assertTrue(findings)
        self.assertNotIn(token, " ".join(findings))
        self.assertFalse(inspect_file(".env.example", b"ANTHROPIC_API_KEY=\n"))
