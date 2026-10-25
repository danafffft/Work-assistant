"""Local preferences only. Never persist tokens or passwords."""

import json
import os
from pathlib import Path
import re
import urllib.parse


def path():
    root = Path(os.getenv("LOCALAPPDATA") or (Path.home() / ".local" / "share"))
    return root / "WorkAssistant" / "profile.json"


def validate(data):
    email = str(data.get("email", "")).strip()
    url = str(data.get("url", "")).strip().rstrip("/")
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise ValueError("Invalid email")
    if url:
        parsed = urllib.parse.urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid Jira URL")
    from zoneinfo import ZoneInfo

    timezone = str(data.get("timezone", "Europe/Kyiv"))
    try:
        ZoneInfo(timezone)
    except Exception:
        raise ValueError("Invalid timezone")
    start, end = int(data.get("startHour", 9)), int(data.get("endHour", 18))
    lunch_start, lunch_end = int(data.get("lunchStart", 13)), int(
        data.get("lunchEnd", 14)
    )
    interval = int(data.get("refreshSeconds", 30))
    weekdays = data.get("weekdays", [0, 1, 2, 3, 4])
    if not 0 <= start < end <= 24 or not 0 <= lunch_start <= lunch_end <= 24:
        raise ValueError("Invalid hours")
    if (
        not 30 <= interval <= 3600
        or not isinstance(weekdays, list)
        or not weekdays
        or any(type(day) != int or not 0 <= day <= 6 for day in weekdays)
    ):
        raise ValueError("Invalid schedule")
    auto_accept = data.get("autoAccept", True)
    if type(auto_accept) is not bool:
        raise ValueError("Invalid auto accept")
    client_id = str(data.get("teamsClientId", "")).strip()
    if client_id and not re.fullmatch(r"[0-9a-fA-F-]{36}", client_id):
        raise ValueError("Invalid client ID")
    return {
        "email": email,
        "url": url,
        "timezone": timezone,
        "startHour": start,
        "endHour": end,
        "lunchStart": lunch_start,
        "lunchEnd": lunch_end,
        "weekdays": sorted(set(weekdays)),
        "refreshSeconds": interval,
        "autoAccept": auto_accept,
        "teamsClientId": client_id,
    }


def load():
    try:
        return validate(json.loads(path().read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError):
        return validate({})


def save(data):
    profile = validate(data)
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(target)
    return profile
