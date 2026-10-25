"""Per-profile local workspace. No application data is stored in the checkout."""

from contextlib import contextmanager
import json
import sqlite3
import uuid
from datetime import datetime, timezone
import local_profile


@contextmanager
def connection():
    path = local_profile.path().with_name("workspace.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute(
        "CREATE TABLE IF NOT EXISTS documents (owner TEXT, kind TEXT, id TEXT, body TEXT, PRIMARY KEY(owner,kind,id))"
    )
    try:
        with db:
            yield db
    finally:
        db.close()


def owner():
    return local_profile.load()["email"].casefold() or "local-default"


def items(kind):
    with connection() as db:
        return [
            json.loads(row[0])
            for row in db.execute(
                "SELECT body FROM documents WHERE owner=? AND kind=?", (owner(), kind)
            )
        ]


def get(kind, identity):
    with connection() as db:
        row = db.execute(
            "SELECT body FROM documents WHERE owner=? AND kind=? AND id=?",
            (owner(), kind, identity),
        ).fetchone()
        return json.loads(row[0]) if row else None


def put(kind, item, journal=True):
    before = get(kind, item["id"]) if journal else None
    with connection() as db:
        db.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?)",
            (owner(), kind, item["id"], json.dumps(item)),
        )
        if journal:
            entry = {
                "id": str(uuid.uuid4()),
                "at": datetime.now(timezone.utc).isoformat(),
                "kind": kind,
                "target": item["id"],
                "before": before,
                "after": item,
                "undone": False,
            }
            db.execute(
                "INSERT INTO documents VALUES (?,?,?,?)",
                (owner(), "journal", entry["id"], json.dumps(entry)),
            )
    return item


def undo(identity):
    entry = get("journal", identity)
    if (
        not entry
        or entry.get("kind") == "external"
        or entry["undone"]
        or get(entry["kind"], entry["target"]) != entry["after"]
    ):
        raise ValueError("Зміни вже скасовані або об’єкт змінено пізніше.")
    with connection() as db:
        if entry["before"] is None:
            db.execute(
                "DELETE FROM documents WHERE owner=? AND kind=? AND id=?",
                (owner(), entry["kind"], entry["target"]),
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO documents VALUES (?,?,?,?)",
                (owner(), entry["kind"], entry["target"], json.dumps(entry["before"])),
            )
        entry["undone"] = True
        db.execute(
            "UPDATE documents SET body=? WHERE owner=? AND kind=? AND id=?",
            (json.dumps(entry), owner(), "journal", identity),
        )


def apply_rules(messages):
    rules = items("rule")
    for message in messages:
        address = (
            message.get("from", {})
            .get("emailAddress", {})
            .get("address", "")
            .casefold()
        )
        for rule in rules:
            if rule.get("enabled", True) and address == rule["sender"]:
                message.update(category=rule["category"], priority=rule["priority"])
    return messages


def ingest(tasks):
    result = []
    for task in tasks:
        existing = get("task", task["id"])
        status = (
            existing.get("status")
            if existing
            else ("candidate" if task["source"].startswith("Teams") else "active")
        )
        merged = {
            **task,
            "status": status or "active",
            "pin": existing.get("pin") if existing else None,
        }
        put("task", merged, journal=False)
    remote_ids = {task["id"] for task in tasks}
    # Do not schedule stale remote work when its source is unavailable or no longer returns it.
    for task in items("task"):
        if (
            task.get("source") in ("Вручну", "Лист · відповісти", "Лист · очікування")
            or task["id"] in remote_ids
        ):
            if (
                task.get("status") == "active"
                and task.get("pin")
                and datetime.fromisoformat(task["pin"]["end"])
                <= datetime.now(timezone.utc)
            ):
                task = {**task, "pin": None}
                put("task", task)
            result.append(task)
    return result


def record_external(title, outcome):
    """Audit only: sent RSVP and Outlook writes cannot be undone by local history."""
    entry = {
        "id": str(uuid.uuid4()),
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": "external",
        "target": "",
        "before": None,
        "after": {"title": title, "outcome": outcome},
        "undone": False,
    }
    put("journal", entry, journal=False)
