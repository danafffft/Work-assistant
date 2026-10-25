"""Local preferences only. Never persist tokens or passwords."""
import json
import os
from pathlib import Path
import re
import urllib.parse


def path():
    root = Path(os.getenv('LOCALAPPDATA') or (Path.home() / '.local' / 'share'))
    return root / 'WorkAssistant' / 'profile.json'


def validate(data):
    email = str(data.get('email', '')).strip()
    url = str(data.get('url', '')).strip().rstrip('/')
    if email and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('Invalid email')
    if url:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Invalid Jira URL')
    return {'email': email, 'url': url}


def load():
    try:
        return validate(json.loads(path().read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError, AttributeError):
        return {'email': '', 'url': ''}


def save(data):
    profile = validate(data)
    target = path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(profile, ensure_ascii=False), encoding='utf-8')
    try: temporary.chmod(0o600)
    except OSError: pass
    temporary.replace(target)
    return profile
