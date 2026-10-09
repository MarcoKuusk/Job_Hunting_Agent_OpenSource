"""Offline tests for one-click preparation and browser-based setup."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import scripts.bootstrap as bootstrap
import src.config as source_config
import webapp.app as web


class GuidedConnectionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = self.root / ".env"
        self.credentials = self.root / "credentials"
        self.saved_env = {name: os.environ.get(name) for name in
                          list(web.CONNECTION_FIELDS.values()) + ["GOOGLE_SERVICE_ACCOUNT_FILE"]}
        self.patches = [
            patch.object(web, "PROJECT_ROOT", self.root),
            patch.object(web, "ENV_PATH", self.env),
            patch.object(web, "CREDENTIALS_DIR", self.credentials),
            patch.object(source_config, "PROJECT_ROOT", self.root),
        ]
        for item in self.patches:
            item.start()
        self.client = web.app.test_client()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        for name, value in self.saved_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.temp.cleanup()

    def test_secret_values_are_saved_but_never_returned(self):
        secret = "test-secret-value-123"
        response = self.client.post("/api/connections", json={
            "anthropic_key": secret,
            "google_sheet_id": "test-sheet-id",
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(secret, self.env.read_text(encoding="utf-8"))
        self.assertNotIn(secret, response.get_data(as_text=True))
        status = self.client.get("/api/connections").get_data(as_text=True)
        self.assertNotIn(secret, status)
        self.assertIn('"anthropic_key":true', status)

    def test_status_and_cross_site_requests_do_not_expose_or_change_secrets(self):
        secret = "another-test-secret-456"
        self.client.post("/api/connections", json={
            "anthropic_key": secret,
            "google_sheet_id": "private-sheet-id",
        })
        status = self.client.get("/api/status").get_data(as_text=True)
        self.assertNotIn(secret, status)
        self.assertNotIn("private-sheet-id", status)

        blocked = self.client.post(
            "/api/connections",
            json={"anthropic_key": "replacement"},
            headers={"Origin": "https://unrelated.example"},
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertIn(secret, self.env.read_text(encoding="utf-8"))


    def test_line_breaks_are_rejected(self):
        response = self.client.post("/api/connections", json={
            "anthropic_key": "first\nsecond",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.env.exists())

    def test_google_json_is_validated_and_saved(self):
        payload = {
            "type": "service_account",
            "project_id": "example-project",
            "private_key": "not-a-real-private-key",
            "client_email": "service-account-email",
        }
        response = self.client.post(
            "/api/upload-google-credentials",
            data={"credentials": (io.BytesIO(json.dumps(payload).encode()), "key.json")},
            content_type="multipart/form-data",
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["configured"]["google_service_email"], "service-account-email")
        saved = self.credentials / "service_account.json"
        self.assertTrue(saved.is_file())
        self.assertNotIn("private_key", response.get_data(as_text=True))
        self.assertIn("credentials/service_account.json", self.env.read_text(encoding="utf-8"))

        invalid = self.client.post(
            "/api/upload-google-credentials",
            data={"credentials": (io.BytesIO(b"{}"), "wrong.json")},
            content_type="multipart/form-data",
        )
        self.assertEqual(invalid.status_code, 400)

class LocalStorageTests(unittest.TestCase):
    def test_matches_work_without_google(self):
        row = {
            "Date found": "2026-01-01", "Source": "remoteok", "Title": "Editor",
            "Company": "Example", "Location": "Remote", "Score": 82,
            "Recommendation": "Strong", "Reasons": "Relevant", "Status": "New",
            "Applied on": "", "URL": "https://example.invalid/job",
        }
        config = SimpleNamespace(min_score=lambda: 70, google_sheets_ready=lambda: False)
        with patch.object(web, "load_config", return_value=config), \
             patch.object(web, "_local_job_rows", return_value=[row]):
            response = web.app.test_client().get("/api/matches")
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["storage"], "local")
        self.assertEqual(body["rows"][0]["Title"], "Editor")

    def test_mark_applied_works_without_google(self):
        config = SimpleNamespace(google_sheets_ready=lambda: False)
        with patch.object(web, "load_config", return_value=config), \
             patch("src.jobstore.set_status", return_value=True):
            response = web.app.test_client().post(
                "/api/mark-applied", json={"url": "https://example.invalid/job"}
            )
        body = response.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body["updated"])
        self.assertFalse(body["sheet_updated"])


class BootstrapTests(unittest.TestCase):
    def test_prepare_creates_private_files_without_overwriting_them(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "config").mkdir()
            (root / "scripts").mkdir()
            (root / "requirements.txt").write_text("example\n", encoding="utf-8")
            (root / ".env.example").write_text("KEY=\n", encoding="utf-8")
            (root / "config" / "profile.example.yaml").write_text("name: ''\n", encoding="utf-8")
            (root / "config" / "search.example.yaml").write_text("keywords: []\n", encoding="utf-8")
            (root / "config" / "profile.yaml").write_text("name: Preserved\n", encoding="utf-8")
            venv = root / ".venv"
            venv.mkdir()
            fake_python = venv / "python"
            fake_python.write_text("", encoding="utf-8")

            with patch.object(bootstrap, "ROOT", root), \
                 patch.object(bootstrap, "VENV", venv), \
                 patch.object(bootstrap, "STAMP", venv / ".job-finder-requirements"), \
                 patch.object(bootstrap, "_venv_python", return_value=fake_python):
                (venv / ".job-finder-requirements").write_text(
                    bootstrap._requirements_fingerprint() + "\n", encoding="utf-8"
                )
                result = bootstrap.prepare()

            self.assertEqual(result, fake_python)
            self.assertTrue((root / ".env").is_file())
            self.assertTrue((root / "config" / "search.yaml").is_file())
            self.assertEqual((root / "config" / "profile.yaml").read_text(encoding="utf-8"),
                             "name: Preserved\n")


if __name__ == "__main__":
    unittest.main()
