import json, os, secrets, time, urllib.parse, urllib.request, urllib.error, base64, hashlib, re
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie

ROOT = Path(__file__).parent
CLIENT = os.getenv("MICROSOFT_CLIENT_ID", "")
TENANT = os.getenv("MICROSOFT_TENANT_ID", "common")
REDIRECT = os.getenv("MICROSOFT_REDIRECT_URI", "http://localhost:8000/auth/callback")
SCOPES = "User.Read Mail.ReadWrite Calendars.ReadWrite"
SESSIONS, PENDING = {}, {}
CATEGORIES = [
    "Звіти",
    "Від людей",
    "Навчання",
    "Автоматичні повідомлення",
    "Jira та Confluence",
]
# Remove old assistant labels when saving the merged category.
MANAGED_CATEGORIES = CATEGORIES + ["Jira", "Confluence"]


def has_person_name(name):
    """Conservative name shape, not proof of a human identity."""
    words = name.strip().split()
    if not 2 <= len(words) <= 4:
        return False
    system_words = {
        "dell",
        "manageengine",
        "oputils",
        "rogue",
        "detection",
        "tool",
        "alert",
        "alerts",
        "system",
        "service",
        "support",
        "team",
        "admin",
        "administrator",
        "notification",
        "notifications",
        "microsoft",
        "office",
        "helpdesk",
        "monitoring",
        "security",
        "company",
        "newsletter",
        "jira",
        "confluence",
        "система",
        "підтримка",
        "команда",
        "служба",
    }
    for word in words:
        if word.casefold() in system_words:
            return False
        parts = re.split("[-’']", word)
        if not all(
            part.isalpha()
            and part[0].isupper()
            and (len(part) == 1 or not part.isupper())
            for part in parts
        ):
            return False
    return True


def classify(m):
    sender = m.get("from", {}).get("emailAddress", {})
    address = sender.get("address", "").lower()
    name = sender.get("name", "")
    subject = m.get("subject", "").lower()
    text = address + " " + subject
    automated = any(
        w in (name + " " + subject).casefold()
        for w in ("manageengine", "oputils", "rogue detection")
    ) or bool(
        re.match(
            r"^(alert(?:s)?(?: from|:|\s*-)|automatic notification|автоматичне повідомлення)",
            subject,
        )
    )
    category = "Автоматичні повідомлення"
    if m.get("hasAttachments") is True:
        category = "Звіти"
    elif "jira" in text or "confluence" in text:
        category = "Jira та Confluence"
    elif automated:
        category = "Автоматичні повідомлення"
    elif any(
        w in text
        for w in (
            "навчання",
            "вебінар",
            "курс",
            "training",
            "webinar",
            "course",
            "learning",
        )
    ):
        category = "Навчання"
    elif any(
        w in address
        for w in ("noreply", "no-reply", "notification", "newsletter", "donotreply")
    ):
        category = "Автоматичні повідомлення"
    elif has_person_name(name):
        category = "Від людей"
    urgent = m.get("importance") == "high" or any(
        w in subject for w in ("терміново", "urgent", "критич", "blocker", "asap")
    )
    return {
        **m,
        "category": category,
        "priority": (
            "high"
            if urgent
            else "low" if category == "Автоматичні повідомлення" else "normal"
        ),
        "meeting": m.get("@odata.type", "").endswith("eventMessageRequest"),
    }


def request(
    url, data=None, token=None, method=None, form=False, headers=None, no_redirect=False
):
    headers = {**(headers or {}), "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["Prefer"] = 'outlook.timezone="UTC"'
    if data is not None:
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
        data = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(
                req.full_url, code, "Redirect refused", headers, fp
            )

    opener = (
        urllib.request.build_opener(NoRedirect())
        if no_redirect or token
        else urllib.request.build_opener()
    )
    with opener.open(
        urllib.request.Request(url, data=data, headers=headers, method=method),
        timeout=30,
    ) as r:
        raw = r.read()
        return json.loads(raw) if raw else {}


def graph(s, path, data=None, method=None):
    if s["expires"] < time.time():
        raise ValueError("Session expired")
    return request("https://graph.microsoft.com/v1.0" + path, data, s["token"], method)


def can_accept(event, schedule):
    # Recurrences and all-day invitations need manual review. Fail closed on incomplete schedules.
    if event.get("recurrence") or event.get("isAllDay") or event.get("isCancelled"):
        return False
    slots = schedule.get("value", [])
    if len(slots) != 1 or slots[0].get("error") or "scheduleItems" not in slots[0]:
        return False
    return all(item.get("status") == "free" for item in slots[0]["scheduleItems"])


def auto_accept(s, m):
    path = "/me/messages/" + urllib.parse.quote(m["id"], safe="")
    try:
        event = graph(s, path + "/microsoft.graph.eventMessageRequest/event")
        if event.get("responseStatus", {}).get("response") in ("accepted", "organizer"):
            return "Вже прийнято"
        if event.get("recurrence") or event.get("isAllDay") or event.get("isCancelled"):
            return "Потрібен ручний перегляд"
        start, end = event["start"], event["end"]
        if not start.get("dateTime") or not end.get("dateTime"):
            return "Час невідомий"
        # Past invitations are never accepted automatically.
        from datetime import datetime, timezone

        # getSchedule understands the original Graph timezone, unlike naive local parsing.
        if start.get("timeZone") != "UTC":
            return "Часовий пояс потребує ручної перевірки"
        if datetime.fromisoformat(start["dateTime"].rstrip("Z")).replace(
            tzinfo=timezone.utc
        ) <= datetime.now(timezone.utc):
            return "Минула зустріч — ручний перегляд"
        profile = graph(s, "/me?$select=mail,userPrincipalName")
        address = profile.get("mail") or profile["userPrincipalName"]
        schedule = graph(
            s,
            "/me/calendar/getSchedule",
            {
                "schedules": [address],
                "startTime": start,
                "endTime": end,
                "availabilityViewInterval": 5,
            },
            "POST",
        )
        # Existing matching event may itself mark the slot tentative: conservatively leave for manual review.
        if not can_accept(event, schedule):
            return "Конфлікт або час недоступний — ручний перегляд"
        graph(s, path + "/accept", {"comment": "", "sendResponse": True}, "POST")
        return "Автоматично прийнято"
    except (ValueError, KeyError, urllib.error.URLError):
        return "Не вдалося перевірити календар — ручний перегляд"


class Handler(BaseHTTPRequestHandler):
    def allowed_request(self):
        host = self.headers.get("Host", "")
        if host not in (
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        ):
            self.send({"error": "Недозволена адреса запиту."}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin != "http://" + host:
            self.send({"error": "Недозволене джерело запиту."}, 403)
            return False
        return True

    def log_message(self, *_):
        pass

    def send(self, body, status=200, mime="application/json", headers=None):
        raw = (
            json.dumps(body, ensure_ascii=False).encode()
            if mime == "application/json"
            else body
        )
        self.send_response(status)
        for k, v in {
            "Content-Type": mime + "; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            **(headers or {}),
        }.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def cookie(self, name):
        c = SimpleCookie()
        c.load(self.headers.get("Cookie", ""))
        return c[name].value if name in c else ""

    def session(self):
        return SESSIONS.get(self.cookie("session"))

    def do_GET(self):
        if not self.allowed_request():
            return
        try:
            self.get()
        except Exception:
            self.send(
                {
                    "error": "Помилка Microsoft. Перевірте налаштування та дозволи, повторіть вхід."
                },
                502,
            )

    def get(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/auth/login":
            if not CLIENT:
                return self.send(
                    {"error": "Задайте MICROSOFT_CLIENT_ID згідно README."}, 400
                )
            for key in list(PENDING):
                if PENDING[key][1] < time.time():
                    PENDING.pop(key, None)
            state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
            PENDING[state] = (verifier, time.time() + 600)
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                .decode()
                .rstrip("=")
            )
            q = urllib.parse.urlencode(
                dict(
                    client_id=CLIENT,
                    response_type="code",
                    redirect_uri=REDIRECT,
                    scope=SCOPES,
                    state=state,
                    code_challenge=challenge,
                    code_challenge_method="S256",
                )
            )
            return self.send(
                b"",
                302,
                "text/plain",
                {
                    "Location": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize?{q}",
                    "Set-Cookie": f"oauth_state={state}; HttpOnly; SameSite=Lax; Path=/; Max-Age=600",
                },
            )
        if url.path == "/auth/callback":
            q = urllib.parse.parse_qs(url.query)
            state = q.get("state", [""])[0]
            p = PENDING.pop(state, None)
            if (
                not p
                or p[1] < time.time()
                or not secrets.compare_digest(self.cookie("oauth_state"), state)
                or "code" not in q
            ):
                return self.send({"error": "Вхід скасовано або прострочено."}, 400)
            data = dict(
                client_id=CLIENT,
                code=q["code"][0],
                grant_type="authorization_code",
                redirect_uri=REDIRECT,
                code_verifier=p[0],
                scope=SCOPES,
            )
            if os.getenv("MICROSOFT_CLIENT_SECRET"):
                data["client_secret"] = os.environ["MICROSOFT_CLIENT_SECRET"]
            tokens = request(
                f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
                data,
                form=True,
            )
            sid = secrets.token_urlsafe(32)
            SESSIONS[sid] = dict(
                token=tokens["access_token"],
                expires=time.time() + tokens["expires_in"],
                csrf=secrets.token_urlsafe(32),
                messages={},
            )
            return self.send(
                b"",
                302,
                "text/plain",
                {
                    "Location": "/",
                    "Set-Cookie": f"session={sid}; HttpOnly; SameSite=Strict; Path=/"
                    + ("; Secure" if REDIRECT.startswith("https:") else ""),
                },
            )
        if url.path == "/api/status":
            import local_profile

            s = self.session()
            cookie_headers = {}
            import teams_connection

            if not s or s["expires"] < time.time():
                sid = secrets.token_urlsafe(32)
                s = dict(
                    mode="profile",
                    expires=time.time() + 86400,
                    csrf=secrets.token_urlsafe(32),
                    messages={},
                )
                SESSIONS[sid] = s
                cookie_headers["Set-Cookie"] = (
                    f"session={sid}; HttpOnly; SameSite=Strict; Path=/"
                )
            profile = local_profile.load()
            if "jira" not in s:
                s["jira"] = profile
            connected = s.get("mode") != "profile"
            return self.send(
                dict(
                    connected=connected,
                    configured=bool(CLIENT),
                    desktop=os.name == "nt",
                    mode=s.get("mode", "graph"),
                    csrf=s["csrf"],
                    profile=profile,
                    jiraConnected=bool(s.get("jira", {}).get("token")),
                    teams=teams_connection.public_status(s),
                ),
                headers=cookie_headers,
            )
        if url.path == "/api/update":
            try:
                release = request(
                    "https://api.github.com/repos/danafffft/Work-assistant/releases/latest",
                    headers={"User-Agent": "WorkAssistant/1.0.0"},
                )
                return self.send(
                    {
                        "current": "1.0.0",
                        "latest": release.get("tag_name"),
                        "url": "https://github.com/danafffft/Work-assistant/releases/latest",
                    }
                )
            except Exception:
                return self.send(
                    {
                        "current": "1.0.0",
                        "latest": None,
                        "url": "https://github.com/danafffft/Work-assistant",
                        "message": "Опублікований інсталятор не знайдено або GitHub недоступний. Оновлення з вихідного коду — на сторінці проєкту.",
                    }
                )
        if url.path == "/api/workspace":
            s = self.session()
            if not s or s["expires"] < time.time():
                return self.send({"error": "Повторіть вхід."}, 401)
            import workhub

            return self.send(workhub.read(s))
        if url.path == "/api/messages":
            s = self.session()
            if not s or s["expires"] < time.time() or s.get("mode") == "profile":
                return self.send({"error": "Підключіть Outlook повторно."}, 401)
            if s.get("mode") == "desktop":
                import desktop_outlook

                raw, limited = desktop_outlook.messages(s["store"])
                messages = [classify(m) for m in raw]
                import workspace_data

                messages = [
                    {**m, **s.get("overrides", {}).get(m["id"], {})}
                    for m in workspace_data.apply_rules(messages)
                ]
                s["messages"] = {m["id"]: m for m in messages}
                return self.send({"messages": messages, "limited": limited})
            result = graph(
                s,
                "/me/mailFolders/inbox/messages?$top=100&$orderby=receivedDateTime%20desc",
            )
            messages = [classify(m) for m in result["value"]]
            import workspace_data

            messages = [
                {**m, **s.get("overrides", {}).get(m["id"], {})}
                for m in workspace_data.apply_rules(messages)
            ]
            s["messages"] = {m["id"]: m for m in messages}
            return self.send(
                {"messages": messages, "limited": bool(result.get("@odata.nextLink"))}
            )
        if url.path == "/api/plan":
            session = self.session()
            if (
                not session
                or session["expires"] < time.time()
                or session.get("mode") == "profile"
            ):
                return self.send({"error": "Підключіть Outlook."}, 401)
            from datetime import datetime, timezone, timedelta
            from integrations import jira_tasks
            from planning import build_plan
            import local_profile
            import teams_connection

            session["lastPlanFresh"] = False
            statuses, tasks = {}, []
            # An unavailable calendar prevents creating a misleading conflict-free plan.
            if session.get("mode") == "desktop":
                import desktop_outlook

                events = desktop_outlook.calendar_events(session["store"])
            else:
                now = datetime.now(timezone.utc)
                query = urllib.parse.urlencode(
                    {
                        "startDateTime": now.isoformat(),
                        "endDateTime": (now + timedelta(days=7)).isoformat(),
                        "$top": 1000,
                    }
                )
                result = graph(session, "/me/calendarView?" + query)
                if result.get("@odata.nextLink"):
                    raise ValueError("Calendar incomplete")
                events = [
                    {
                        "id": e["id"],
                        "title": e.get("subject", "Нарада"),
                        "start": e["start"]["dateTime"].rstrip("Z") + "+00:00",
                        "end": e["end"]["dateTime"].rstrip("Z") + "+00:00",
                        "busy": e.get("showAs") != "free",
                    }
                    for e in result.get("value", [])
                    if not e.get("isCancelled")
                ]
            for key, loader in [
                ("jira", lambda: jira_tasks(request, session.get("jira"))),
                ("teams", lambda: teams_connection.tasks(session, request)),
            ]:
                try:
                    cached = session.setdefault("sourceCache", {}).get(key)
                    ttl = 300 if key == "teams" else 60
                    if cached and time.time() - cached["at"] < ttl:
                        loaded, statuses[key] = cached["tasks"], cached["status"]
                    else:
                        loaded, statuses[key] = loader()
                        if (
                            key != "teams"
                            or teams_connection.public_status(session)["status"]
                            == "connected"
                        ):
                            session["sourceCache"][key] = {
                                "at": time.time(),
                                "tasks": loaded,
                                "status": statuses[key],
                            }
                    tasks.extend(loaded)
                except Exception:
                    statuses[key] = (
                        "Не вдалося оновити джерело. Перевірте адресу, доступ і дозволи; його задач немає у графіку."
                    )
            tasks = [
                task
                for task in tasks
                if task["id"] not in session.get("dismissedTasks", set())
            ]
            import workspace_data

            all_tasks = workspace_data.ingest(tasks)
            tasks = [
                t
                for t in all_tasks
                if t.get("status") == "active"
                and not t.get("pin")
                and t.get("source") != "Лист · очікування"
            ]
            pinned = [
                {**t, **t["pin"]}
                for t in all_tasks
                if t.get("pin") and t.get("status") == "active"
            ]
            events += [{**t, "busy": True, "pinnedTask": True} for t in pinned]
            preferences = local_profile.load()
            plan = build_plan(
                tasks,
                events,
                timezone=preferences["timezone"],
                start_hour=preferences["startHour"],
                end_hour=preferences["endHour"],
                weekdays=preferences["weekdays"],
                lunch_start=preferences["lunchStart"],
                lunch_end=preferences["lunchEnd"],
            )
            plan["generatedAt"] = datetime.now(timezone.utc).isoformat()
            plan["calendarValidUntil"] = (
                datetime.now(timezone.utc) + timedelta(seconds=120)
            ).isoformat()
            plan["horizonEnd"] = (
                datetime.now(timezone.utc) + timedelta(days=7)
            ).isoformat()
            calendar_only = [
                e for e in events if not e.get("pinnedTask") and e.get("busy", True)
            ]
            for event in plan["meetings"]:
                if event.get("pinnedTask"):
                    event["conflict"] = any(
                        datetime.fromisoformat(other["start"])
                        < datetime.fromisoformat(event["end"])
                        and datetime.fromisoformat(other["end"])
                        > datetime.fromisoformat(event["start"])
                        for other in calendar_only
                    )
            session["lastPlanFresh"] = True
            session["lastPlan"] = plan
            return self.send({**plan, "sources": statuses, "tasks": all_tasks})
        files = {
            "/hub.js": ("hub.js", "text/javascript"),
            "/": ("index.html", "text/html"),
            "/app.js": ("app.js", "text/javascript"),
            "/style.css": ("style.css", "text/css"),
        }
        if url.path in files:
            name, mime = files[url.path]
            return self.send((ROOT / "web" / name).read_bytes(), mime=mime)
        self.send({"error": "Не знайдено"}, 404)

    def do_POST(self):
        if not self.allowed_request():
            return
        if self.path == "/api/connect":
            # Same-origin browser requests only; no ambient Outlook access from other sites.
            if self.headers.get("Origin") != "http://" + self.headers.get("Host", ""):
                return self.send(
                    {"error": "Підключення доступне лише з вікна застосунку."}, 403
                )
            if os.name != "nt":
                return self.send(
                    {
                        "error": "Для цього підключення потрібні Windows та класичний Outlook."
                    },
                    400,
                )
            try:
                import desktop_outlook

                store = desktop_outlook.connect()
                sid = secrets.token_urlsafe(32)
                previous = self.session()
                jira_settings = dict(previous.get("jira", {})) if previous else {}
                SESSIONS.pop(self.cookie("session"), None)
                SESSIONS[sid] = dict(
                    mode="desktop",
                    teams=previous.get("teams", {}) if previous else {},
                    jira=jira_settings,
                    store=store,
                    expires=time.time() + 86400,
                    csrf=secrets.token_urlsafe(32),
                    messages={},
                )
                return self.send(
                    {"ok": True},
                    headers={
                        "Set-Cookie": f"session={sid}; HttpOnly; SameSite=Strict; Path=/"
                    },
                )
            except Exception:
                return self.send(
                    {
                        "error": "Не вдалося підключити класичний Outlook. Відкрийте його, перевірте профіль і дозволи організації."
                    },
                    503,
                )
        s = self.session()
        if (
            not s
            or s["expires"] < time.time()
            or not secrets.compare_digest(
                self.headers.get("X-CSRF-Token", ""), s["csrf"]
            )
        ):
            return self.send({"error": "Потрібен чинний сеанс."}, 403)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 8192:
                return self.send({"error": "Запит завеликий"}, 413)
            body = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(body, dict):
                return self.send({"error": "Неправильний формат запиту."}, 400)
            if self.path == "/api/workspace":
                import workhub

                try:
                    return self.send(workhub.action(s, body, CATEGORIES))
                except (ValueError, KeyError, TypeError) as error:
                    return self.send({"error": str(error)}, 400)
            if self.path == "/api/teams/start":
                import teams_connection, local_profile

                try:
                    return self.send(
                        teams_connection.start(s, local_profile.load()["teamsClientId"])
                    )
                except ImportError:
                    return self.send(
                        {"error": "Оновіть залежності через Start-WorkAssistant.bat."},
                        400,
                    )
                except Exception:
                    return self.send(
                        {
                            "error": "Не вдалося почати Teams-вхід. Перевірте client ID та дозволи IT."
                        },
                        400,
                    )
            if self.path == "/api/teams/disconnect":
                s.pop("teams", None)
                s.pop("sourceCache", None)
                return self.send({"ok": True})
            if self.path == "/api/task-dismiss":
                task_id = str(body.get("id", ""))
                if not task_id or len(task_id) > 2048:
                    return self.send({"error": "Неправильна задача."}, 400)
                s.setdefault("dismissedTasks", set()).add(task_id)
                return self.send({"ok": True})
            if self.path == "/api/tasks-restore":
                s.pop("dismissedTasks", None)
                return self.send({"ok": True})
            if self.path == "/api/override":
                message = s["messages"].get(body.get("id"))
                if (
                    not message
                    or body.get("category") not in CATEGORIES
                    or body.get("priority") not in ("high", "normal", "low")
                ):
                    return self.send(
                        {"error": "Оновіть лист або перевірте категорію."}, 400
                    )
                override = {"category": body["category"], "priority": body["priority"]}
                s.setdefault("overrides", {})[message["id"]] = override
                message.update(override)
                return self.send({"ok": True, "message": message})
            if self.path == "/api/profile":
                import local_profile

                try:
                    profile = local_profile.validate(body)
                except (ValueError, TypeError):
                    return self.send(
                        {
                            "error": "Перевірте email, адресу Jira, часовий пояс та межі графіка."
                        },
                        400,
                    )
                old_profile = local_profile.load()
                try:
                    local_profile.save(profile)
                except OSError:
                    return self.send(
                        {"error": "Не вдалося зберегти локальний профіль."}, 500
                    )
                if old_profile.get("teamsClientId") != profile["teamsClientId"]:
                    s.pop("teams", None)
                s.pop("sourceCache", None)
                previous = s.get("jira", {})
                same_identity = (
                    previous.get("url") == profile["url"]
                    and previous.get("email") == profile["email"]
                )
                token = str(body.get("token", "")).strip() or (
                    previous.get("token", "") if same_identity else ""
                )
                s["jira"] = {**profile, "token": token}
                return self.send(
                    {"ok": True, "profile": profile, "jiraConnected": bool(token)}
                )
            if self.path == "/api/jira-settings":
                jira_url = str(body.get("url", "")).strip().rstrip("/")
                parsed = urllib.parse.urlsplit(jira_url)
                if (
                    parsed.scheme != "https"
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                ):
                    return self.send(
                        {
                            "error": "Вкажіть HTTPS-адресу вашого сервера Jira без пароля у посиланні."
                        },
                        400,
                    )
                token = str(body.get("token", "")).strip()
                if not token:
                    return self.send(
                        {
                            "error": "Вкажіть API-токен у цьому вікні. Не надсилайте його у чат."
                        },
                        400,
                    )
                s["jira"] = {
                    "url": jira_url,
                    "email": str(body.get("email", "")).strip(),
                    "token": token,
                }
                return self.send({"ok": True})
            if self.path == "/api/logout":
                SESSIONS.pop(self.cookie("session"), None)
                return self.send({"ok": True})
            if self.path == "/api/meetings":
                import local_profile

                if not local_profile.load()["autoAccept"]:
                    return self.send(
                        {
                            "results": {
                                m["id"]: "Автоприйняття вимкнено"
                                for m in s["messages"].values()
                                if m["meeting"]
                            }
                        }
                    )
                results = {}
                for m in list(s["messages"].values()):
                    if not m["meeting"]:
                        continue
                    if s.get("mode") == "desktop":
                        import desktop_outlook

                        try:
                            results[m["id"]] = desktop_outlook.accept_if_free(
                                s["store"], m["id"]
                            )
                        except Exception:
                            results[m["id"]] = "Помилка Outlook — ручний перегляд"
                    else:
                        results[m["id"]] = auto_accept(s, m)
                import workspace_data

                for message_id, outcome in results.items():
                    if outcome == "Автоматично прийнято":
                        workspace_data.record_external(
                            s["messages"][message_id].get("subject", "Нарада"), outcome
                        )
                return self.send({"results": results})
            m = s["messages"].get(body.get("id"))
            if not m:
                return self.send({"error": "Оновіть список листів."}, 400)
            path = "/me/messages/" + urllib.parse.quote(m["id"], safe="")
            if s.get("mode") == "desktop":
                import desktop_outlook

                try:
                    if self.path == "/api/categorize":
                        desktop_outlook.categorize(s["store"], m, MANAGED_CATEGORIES)
                        import workspace_data

                        workspace_data.record_external(
                            m.get("subject", "Лист"), "Категорії Outlook збережено"
                        )
                    elif self.path == "/api/open":
                        desktop_outlook.open_message(s["store"], m["id"])
                    else:
                        return self.send({"error": "Невідома дія"}, 400)
                except Exception:
                    return self.send(
                        {
                            "error": "Outlook не виконав дію. Перевірте доступ і оновіть пошту."
                        },
                        502,
                    )
                return self.send({"ok": True})
            if self.path == "/api/categorize":
                current = graph(s, path + "?$select=categories")
                categories = [
                    c
                    for c in current.get("categories", [])
                    if c not in MANAGED_CATEGORIES
                ]
                graph(
                    s,
                    path,
                    {
                        "categories": categories + [m["category"]],
                        "importance": m["priority"],
                    },
                    "PATCH",
                )
                import workspace_data

                workspace_data.record_external(
                    m.get("subject", "Лист"), "Категорії Outlook збережено"
                )
            else:
                return self.send({"error": "Невідома дія"}, 400)
            self.send({"ok": True})
        except (ValueError, KeyError, TypeError, urllib.error.URLError):
            self.send(
                {
                    "error": "Дію не виконано. Перевірте дозволи Microsoft та оновіть пошту."
                },
                502,
            )


if __name__ == "__main__":
    print("Work assistant: http://localhost:8000", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
