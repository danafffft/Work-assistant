import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import local_profile
import workspace_data as data
import workhub


class WorkspaceTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch(
            "local_profile.path", return_value=Path(self.temp.name) / "profile.json"
        )
        self.patch.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.patch.stop)

    def test_local_create_status_and_undo(self):
        workhub.action({}, {"action": "task", "title": "Example task"}, [])
        task = data.items("task")[0]
        workhub.action({}, {"action": "status", "id": task["id"], "status": "done"}, [])
        journal = sorted(data.items("journal"), key=lambda e: e["at"])[-1]
        data.undo(journal["id"])
        self.assertEqual(data.get("task", task["id"])["status"], "active")
        with self.assertRaises(ValueError):
            data.undo(journal["id"])

    def test_teams_candidates_require_approval(self):
        tasks = data.ingest(
            [
                {
                    "id": "teams:1",
                    "title": "Mention",
                    "source": "Teams · згадка",
                    "minutes": 30,
                }
            ]
        )
        self.assertEqual(tasks[0]["status"], "candidate")
        workhub.action(
            {}, {"action": "status", "id": "teams:1", "status": "active"}, []
        )
        self.assertEqual(
            data.ingest(
                [
                    {
                        "id": "teams:1",
                        "title": "Updated",
                        "source": "Teams · згадка",
                        "minutes": 30,
                    }
                ]
            )[0]["status"],
            "active",
        )

    def test_profile_isolation(self):
        local_profile.save({"email": "one@example.com"})
        workhub.action({}, {"action": "task", "title": "Private"}, [])
        local_profile.save({"email": "two@example.com"})
        self.assertEqual(data.items("task"), [])

    def test_sender_rule(self):
        workhub.action(
            {},
            {
                "action": "rule",
                "sender": "sender@example.com",
                "category": "Звіти",
                "priority": "high",
            },
            ["Звіти"],
        )
        m = {
            "from": {"emailAddress": {"address": "Sender@example.com"}},
            "category": "Від людей",
        }
        self.assertEqual(data.apply_rules([m])[0]["category"], "Звіти")

    def test_stale_remote_not_scheduled(self):
        data.ingest(
            [{"id": "jira:1", "title": "Remote", "source": "Jira", "minutes": 30}]
        )
        self.assertEqual(data.ingest([]), [])

    def test_pin_rejects_missing_calendar(self):
        workhub.action({}, {"action": "task", "title": "Example"}, [])
        task = data.items("task")[0]
        with self.assertRaises(ValueError):
            workhub.action(
                {},
                {
                    "action": "pin",
                    "id": task["id"],
                    "start": "2099-10-26T10:00:00+02:00",
                },
                [],
            )

    def test_pin_and_conflict(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        day = datetime.now(ZoneInfo("Europe/Kyiv")) + timedelta(days=1)
        while day.weekday() > 4:
            day += timedelta(days=1)
        start = day.replace(hour=10, minute=0, second=0, microsecond=0).isoformat()
        workhub.action({}, {"action": "task", "title": "First", "minutes": 60}, [])
        first = data.items("task")[0]
        session = {"lastPlan": {"meetings": []}}
        workhub.action(
            session, {"action": "pin", "id": first["id"], "start": start}, []
        )
        self.assertIsNotNone(data.get("task", first["id"])["pin"])
        workhub.action({}, {"action": "task", "title": "Second", "minutes": 60}, [])
        second = next(t for t in data.items("task") if t["id"] != first["id"])
        with self.assertRaises(ValueError):
            workhub.action(
                session, {"action": "pin", "id": second["id"], "start": start}, []
            )

    def test_external_action_is_audit_only(self):
        data.record_external("Fictional subject", "Accepted")
        entry = data.items("journal")[0]
        with self.assertRaises(ValueError):
            data.undo(entry["id"])

    def test_expired_unfinished_block_returns_to_planning(self):
        data.put(
            "task",
            {
                "id": "local:old",
                "title": "Old",
                "source": "Вручну",
                "status": "active",
                "minutes": 30,
                "pin": {
                    "start": "2020-01-01T09:00:00+00:00",
                    "end": "2020-01-01T10:00:00+00:00",
                },
            },
        )
        self.assertIsNone(data.ingest([])[0]["pin"])
