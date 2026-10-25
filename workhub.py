"""Local task, rule, reminder and audit APIs."""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import local_profile
import workspace_data as data


def read(session):
    tasks = data.items("task")
    return {
        "calendarFresh": bool(
            session.get("lastPlanFresh")
            and session.get("lastPlan", {}).get("calendarValidUntil")
            and datetime.fromisoformat(session["lastPlan"]["calendarValidUntil"])
            > datetime.now().astimezone()
        ),
        "tasks": tasks,
        "rules": data.items("rule"),
        "journal": sorted(data.items("journal"), key=lambda e: e["at"], reverse=True)[
            :100
        ],
        "meetings": session.get("lastPlan", {}).get("meetings", []),
    }


def action(session, body, categories):
    operation = body.get("action")
    if operation == "undo":
        data.undo(body["id"])
        return {"ok": True}
    if operation == "rule":
        sender = str(body.get("sender", "")).strip().casefold()
        if (
            "@" not in sender
            or body.get("category") not in categories
            or body.get("priority") not in ("high", "normal", "low")
        ):
            raise ValueError("Перевірте адресу відправника, категорію та пріоритет.")
        data.put(
            "rule",
            {
                "id": sender,
                "sender": sender,
                "category": body["category"],
                "priority": body["priority"],
                "enabled": True,
            },
        )
    elif operation == "rule-disable":
        rule = data.get("rule", body["id"])
        if not rule:
            raise ValueError("Правило не знайдено.")
        data.put("rule", {**rule, "enabled": False})
    elif operation == "task":
        title = str(body.get("title", "")).strip()
        if not title or len(title) > 500:
            raise ValueError("Назва задачі: від 1 до 500 символів.")
        minutes = int(body.get("minutes", 60))
        if not 15 <= minutes <= 2400:
            raise ValueError("Оцінка: 15–2400 хвилин.")
        due = str(body.get("due", "")).strip() or None
        if due:
            datetime.strptime(due, "%Y-%m-%d")
        source = body.get("source", "Вручну")
        if source not in ("Вручну", "Лист · відповісти", "Лист · очікування"):
            raise ValueError("Неправильне джерело.")
        data.put(
            "task",
            {
                "id": "local:" + str(uuid.uuid4()),
                "title": title,
                "minutes": minutes,
                "due": due,
                "rank": 3,
                "source": source,
                "status": "active",
                "pin": None,
            },
        )
    elif operation in ("status", "pin"):
        task = data.get("task", body["id"])
        if not task:
            raise ValueError("Задачу не знайдено.")
        if operation == "status":
            status = body.get("status")
            if status not in ("active", "candidate", "done", "dismissed"):
                raise ValueError("Неправильний статус.")
            data.put(
                "task",
                {
                    **task,
                    "status": status,
                    "pin": None if status != "active" else task.get("pin"),
                },
            )
        else:
            if not body.get("start"):
                data.put("task", {**task, "pin": None})
                return {"ok": True}
            p = local_profile.load()
            zone = ZoneInfo(p["timezone"])
            start = datetime.fromisoformat(body["start"])
            if start.tzinfo is None:
                raise ValueError("Потрібен часовий пояс.")
            start = start.astimezone(zone)
            end = start + timedelta(minutes=task["minutes"])
            if (
                start <= datetime.now(zone)
                or start.weekday() not in p["weekdays"]
                or start.date() != end.date()
                or start.hour < p["startHour"]
                or end.hour + (end.minute / 60) > p["endHour"]
            ):
                raise ValueError("Оберіть майбутній час у межах робочого дня.")
            if (
                p["lunchStart"] < p["lunchEnd"]
                and start.hour + start.minute / 60 < p["lunchEnd"]
                and end.hour + end.minute / 60 > p["lunchStart"]
            ):
                raise ValueError("Цей час перетинається з обідом.")
            if not session.get("lastPlanFresh") or "lastPlan" not in session:
                raise ValueError("Спочатку успішно оновіть календар.")
            plan = session["lastPlan"]
            valid_until = datetime.fromisoformat(plan["calendarValidUntil"])
            if datetime.now(zone) > valid_until:
                raise ValueError("Дані календаря застаріли. Оновіть графік.")
            if end > datetime.fromisoformat(plan["horizonEnd"]):
                raise ValueError("Час поза перевіреним тижнем календаря.")
            busy = list(session["lastPlan"]["meetings"])
            for other in data.items("task"):
                if (
                    other["id"] != task["id"]
                    and other.get("pin")
                    and other.get("status") == "active"
                ):
                    busy.append(other["pin"])
            for event in busy:
                if event.get("pinnedTask") and event.get("id") == task["id"]:
                    continue
                if (
                    event.get("busy", True)
                    and datetime.fromisoformat(event["start"]) < end
                    and datetime.fromisoformat(event["end"]) > start
                ):
                    raise ValueError("Конфлікт із зустріччю або закріпленою задачею.")
            data.put(
                "task",
                {
                    **task,
                    "status": "active",
                    "pin": {"start": start.isoformat(), "end": end.isoformat()},
                },
            )
    else:
        raise ValueError("Невідома дія.")
    return {"ok": True}
