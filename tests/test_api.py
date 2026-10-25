import json
import threading
import time
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from http.server import ThreadingHTTPServer
import app


class ApiTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self.temp = tempfile.TemporaryDirectory()
        self.profile_patch = patch(
            "local_profile.path", return_value=Path(self.temp.name) / "profile.json"
        )
        self.profile_patch.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.profile_patch.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        app.SESSIONS["test-session"] = {
            "mode": "desktop",
            "store": "store",
            "expires": time.time() + 600,
            "csrf": "test-csrf",
            "messages": {},
        }

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        app.SESSIONS.pop("test-session", None)

    def request(self, path, data=None, csrf="test-csrf"):
        headers = {
            "Cookie": "session=test-session",
            "Origin": self.base,
            "X-CSRF-Token": csrf,
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=headers,
        )
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_settings_are_session_only_and_plan_uses_them(self):
        settings = {
            "url": "https://jira.example.com",
            "email": "person@example.com",
            "token": "test-only",
        }
        self.assertEqual(self.request("/api/jira-settings", settings), {"ok": True})
        with patch("desktop_outlook.calendar_events", return_value=[]), patch(
            "integrations.jira_tasks",
            return_value=(
                [{"id": "J-1", "title": "Task", "minutes": 30, "source": "Jira"}],
                "Jira updated",
            ),
        ) as jira:
            result = self.request("/api/plan")
        self.assertTrue(result["draft"])
        self.assertEqual(result["timezone"], "Europe/Kyiv")
        self.assertEqual(jira.call_args.args[1], settings)
        self.assertNotIn("test-only", json.dumps(result))
        self.assertIn("не підключено", result["sources"]["teams"])

    def test_calendar_error_does_not_produce_empty_plan(self):
        with patch("desktop_outlook.calendar_events", side_effect=ValueError("failed")):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request("/api/plan")
        self.assertEqual(error.exception.code, 502)

    def test_settings_require_csrf(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(
                "/api/jira-settings",
                {"url": "https://jira.example.com", "token": "test-only"},
                csrf="wrong",
            )
        self.assertEqual(error.exception.code, 403)

    def test_reject_credentials_in_url(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(
                "/api/jira-settings",
                {"url": "https://user:password@jira.example.com", "token": "test-only"},
            )
        self.assertEqual(error.exception.code, 400)

    def test_profile_persists_preferences_without_token(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory, patch(
            "local_profile.path", return_value=Path(directory) / "profile.json"
        ):
            result = self.request(
                "/api/profile",
                {
                    "email": "person@example.com",
                    "url": "https://example.atlassian.net",
                    "token": "secret-test-only",
                },
            )
            saved = (Path(directory) / "profile.json").read_text()
            self.assertNotIn("secret-test-only", saved)
            self.assertEqual(json.loads(saved)["email"], "person@example.com")
            self.assertEqual(json.loads(saved)["refreshSeconds"], 30)
            self.assertTrue(result["jiraConnected"])
            self.assertNotIn("secret-test-only", json.dumps(result))
            self.assertEqual(
                self.request("/api/status")["profile"]["email"], "person@example.com"
            )

    def test_identity_change_drops_previous_token(self):
        import tempfile
        from pathlib import Path

        app.SESSIONS["test-session"]["jira"] = {
            "email": "old@example.com",
            "url": "https://example.atlassian.net",
            "token": "old-test-token",
        }
        with tempfile.TemporaryDirectory() as directory, patch(
            "local_profile.path", return_value=Path(directory) / "profile.json"
        ):
            result = self.request(
                "/api/profile",
                {"email": "new@example.com", "url": "https://example.atlassian.net"},
            )
            self.assertFalse(result["jiraConnected"])
            self.assertFalse(app.SESSIONS["test-session"]["jira"]["token"])

    def test_auto_accept_off_never_calls_outlook(self):
        app.SESSIONS["test-session"]["messages"] = {
            "one": {"id": "one", "meeting": True}
        }
        with patch("local_profile.load", return_value={"autoAccept": False}), patch(
            "desktop_outlook.accept_if_free"
        ) as accept:
            result = self.request("/api/meetings", {})
        self.assertIn("вимкнено", result["results"]["one"])
        accept.assert_not_called()

    def test_manual_override_is_used_on_refresh(self):
        message = {
            "id": "one",
            "subject": "Notice",
            "from": {"emailAddress": {"address": "noreply@example.com"}},
        }
        app.SESSIONS["test-session"]["messages"] = {"one": app.classify(message)}
        self.request(
            "/api/override", {"id": "one", "category": "Навчання", "priority": "high"}
        )
        with patch("desktop_outlook.messages", return_value=([message], False)):
            result = self.request("/api/messages")
        self.assertEqual(result["messages"][0]["category"], "Навчання")
        self.assertEqual(result["messages"][0]["priority"], "high")

    def test_dismiss_and_restore_tasks_without_changing_jira(self):
        with patch("desktop_outlook.calendar_events", return_value=[]), patch(
            "integrations.jira_tasks",
            return_value=(
                [{"id": "J-1", "title": "Task", "minutes": 30, "source": "Jira"}],
                "Jira updated",
            ),
        ) as jira:
            self.request("/api/task-dismiss", {"id": "J-1"})
            self.assertEqual(self.request("/api/plan")["tasks"], [])
            self.request("/api/tasks-restore", {})
            self.assertEqual(len(self.request("/api/plan")["tasks"]), 1)
            self.assertEqual(jira.call_count, 1)
