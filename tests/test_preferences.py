import unittest
from datetime import datetime
from unittest.mock import Mock
import local_profile
import teams_connection
from planning import build_plan


class Preferences(unittest.TestCase):
    def test_old_profile_gets_defaults(self):
        result = local_profile.validate({"email": "person@example.com", "url": ""})
        self.assertEqual(result["weekdays"], [0, 1, 2, 3, 4])
        self.assertEqual(result["startHour"], 9)

    def test_invalid_settings_rejected(self):
        for data in (
            {"startHour": 18, "endHour": 9},
            {"refreshSeconds": 1},
            {"weekdays": []},
            {"timezone": "Invalid/Zone"},
            {"autoAccept": "false"},
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                local_profile.validate(data)

    def test_custom_weekend_schedule_without_lunch(self):
        plan = build_plan(
            [{"id": "task", "title": "Work", "minutes": 120}],
            [],
            now=datetime.fromisoformat("2026-10-24T08:00:00+03:00"),
            weekdays=[5],
            start_hour=10,
            end_hour=12,
            lunch_start=0,
            lunch_end=0,
            days=1,
        )
        self.assertEqual(len(plan["blocks"]), 2)
        self.assertEqual(datetime.fromisoformat(plan["blocks"][0]["start"]).hour, 10)
        self.assertEqual(plan["backlog"], [])

    def test_teams_public_state_never_returns_token(self):
        import time

        status = teams_connection.public_status(
            {
                "teams": {
                    "status": "connected",
                    "token": "test-secret",
                    "expires": time.time() + 100,
                }
            }
        )
        self.assertEqual(status, {"status": "connected"})

    def test_teams_expiry_blocks_read(self):
        request = Mock()
        tasks, status = teams_connection.tasks(
            {"teams": {"status": "connected", "expires": 0, "token": "test-secret"}},
            request,
        )
        self.assertEqual(tasks, [])
        request.assert_not_called()

    def test_teams_only_explicit_mentions(self):
        import time

        session = {
            "teams": {
                "status": "connected",
                "expires": time.time() + 100,
                "token": "test-secret",
            }
        }
        request = Mock(
            side_effect=[
                {"id": "mine"},
                {"value": [{"id": "chat"}]},
                {
                    "value": [
                        {
                            "id": "m",
                            "body": {"content": "<at>Person</at> do report"},
                            "mentions": [{"mentioned": {"user": {"id": "mine"}}}],
                        },
                        {
                            "id": "n",
                            "body": {"content": "Person do report"},
                            "mentions": [],
                        },
                    ]
                },
            ]
        )
        tasks, status = teams_connection.tasks(session, request)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["source"], "Teams · згадка")


class DeviceLoginTests(unittest.TestCase):
    def test_device_login_keeps_credentials_out_of_public_response(self):
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch, Mock

        client = Mock()
        client.initiate_device_flow.return_value = {
            "user_code": "FICTIONAL",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 600,
        }
        client.acquire_token_by_device_flow.return_value = {
            "access_token": "fictional-token",
            "expires_in": 3600,
        }
        fake_msal = SimpleNamespace(PublicClientApplication=Mock(return_value=client))
        fake_thread = lambda target, daemon: SimpleNamespace(start=target)
        session = {"sourceCache": {"teams": {}}}
        with patch.dict(sys.modules, {"msal": fake_msal}), patch(
            "teams_connection.threading.Thread", side_effect=fake_thread
        ):
            result = teams_connection.start(
                session, "00000000-0000-0000-0000-000000000000"
            )
        self.assertEqual(result, {"status": "connected"})
        self.assertEqual(session["teams"]["token"], "fictional-token")
        self.assertNotIn("sourceCache", session)
        self.assertNotIn("code", session["teams"])
