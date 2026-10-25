import unittest
from datetime import datetime
from planning import build_plan
from integrations import mentioned_tasks, jira_tasks


class PlanningTests(unittest.TestCase):
    now = datetime.fromisoformat("2026-10-26T08:00:00+02:00")

    def test_never_overlaps_meetings_or_lunch(self):
        meetings = [
            {
                "id": "m",
                "title": "Call",
                "start": "2026-10-26T09:00:00+02:00",
                "end": "2026-10-26T10:00:00+02:00",
                "busy": True,
            }
        ]
        result = build_plan(
            [{"id": "task", "title": "Work", "minutes": 480}],
            meetings,
            now=self.now,
            days=1,
        )
        for block in result["blocks"]:
            start, end = datetime.fromisoformat(block["start"]), datetime.fromisoformat(
                block["end"]
            )
            self.assertGreaterEqual(start.hour, 10)
            self.assertFalse(start.hour < 14 and end.hour > 13)
            self.assertLessEqual(end.hour, 18)
        self.assertTrue(result["backlog"])

    def test_deduplicates_and_skips_weekends(self):
        task = {"id": "1", "title": "Task", "minutes": 30}
        result = build_plan(
            [task, task],
            [],
            now=datetime.fromisoformat("2026-10-24T08:00:00+03:00"),
            days=4,
        )
        self.assertEqual(len(result["blocks"]), 1)
        self.assertEqual(
            datetime.fromisoformat(result["blocks"][0]["start"]).weekday(), 0
        )

    def test_explicit_user_id_required(self):
        messages = [
            {
                "id": "1",
                "body": {"content": '<at id="0">Olena</at> зроби звіт'},
                "mentions": [{"mentioned": {"user": {"id": "mine"}}}],
            },
            {"id": "2", "body": {"content": "Olena зроби звіт"}, "mentions": []},
            {
                "id": "3",
                "body": {"content": "Other"},
                "mentions": [{"mentioned": {"user": {"id": "other"}}}],
            },
        ]
        tasks = mentioned_tasks(messages, "mine", "chat")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], "teams:chat:1")
        self.assertNotIn("<at", tasks[0]["title"])

    def test_jira_current_user_query_and_normalization(self):
        from unittest.mock import patch, Mock

        loader = Mock(
            return_value={
                "issues": [
                    {
                        "key": "A-1",
                        "fields": {
                            "summary": "Work",
                            "timeestimate": 7200,
                            "priority": {"id": "2"},
                        },
                    }
                ],
                "isLast": True,
            }
        )
        with patch.dict(
            "os.environ",
            {
                "JIRA_URL": "https://example.atlassian.net",
                "JIRA_EMAIL": "me@example.com",
                "JIRA_API_TOKEN": "test-only",
            },
        ):
            tasks, status = jira_tasks(loader)
        self.assertEqual(tasks[0]["minutes"], 120)
        self.assertIn("currentUser", loader.call_args.args[0])
        self.assertEqual(tasks[0]["source"], "Jira")
