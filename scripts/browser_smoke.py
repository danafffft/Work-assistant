"""Run against a local dev server. All service responses use fictional fixtures."""

import os
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=os.getenv("CHROMIUM_PATH", "/usr/bin/chromium"),
        args=["--no-sandbox"],
    )
    page = browser.new_page(bypass_csp=True, viewport={"width": 1440, "height": 1000})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    calls = {"messages": 0, "meetings": 0}
    preferences = {
        "email": "person@example.com",
        "url": "",
        "refreshSeconds": 30,
        "timezone": "Europe/Kyiv",
    }
    sample = {
        "id": "one",
        "subject": "Test subject",
        "category": "Від людей",
        "priority": "normal",
        "from": {
            "emailAddress": {"name": "Test Person", "address": "person@example.com"}
        },
        "bodyPreview": "<script>never run</script>",
    }

    def route(r):
        path = r.request.url.split("/api/")[1]
        if path == "status":
            data = {
                "connected": True,
                "desktop": True,
                "csrf": "fictional",
                "profile": preferences,
                "teams": {"status": "disconnected"},
            }
        elif path == "messages":
            calls["messages"] += 1
            data = {"messages": [sample], "limited": False}
        elif path == "meetings":
            calls["meetings"] += 1
            data = {"results": {}}
        elif path == "plan":
            data = {
                "sources": {"jira": "Not connected"},
                "blocks": [],
                "meetings": [],
                "backlog": [],
            }
        elif path == "profile":
            body = r.request.post_data_json
            preferences.update(
                {key: value for key, value in body.items() if key != "token"}
            )
            data = {"profile": preferences, "ok": True, "jiraConnected": False}
        else:
            data = {"ok": True}
        r.fulfill(json=data)

    page.route("**/api/**", route)
    page.clock.install()
    page.goto(os.getenv("WA_TEST_URL", "http://127.0.0.1:8004"))
    page.locator("#notice").filter(has_text="Запрошення перевірено").wait_for()
    assert page.locator("#detail script").count() == 0
    page.locator("#profile-nav").click()
    page.locator("#work-start").fill("10")
    page.locator("#work-end").fill("19")
    page.locator("#refresh-seconds").fill("60")
    page.locator("#auto-accept").uncheck()
    page.locator("#jira-form button[type=submit]").click()
    page.locator("#profile-result").filter(has_text="Профіль збережено").wait_for()
    assert preferences["startHour"] == 10
    assert preferences["autoAccept"] is False
    assert page.locator("#auto-toggle").inner_text() == "Авто: 60 с"
    count = calls["messages"]
    page.clock.fast_forward(61000)
    page.wait_for_timeout(100)
    assert calls["messages"] == count + 1
    page.locator("#auto-toggle").click()
    page.clock.fast_forward(61000)
    assert calls["messages"] == count + 1
    page.locator('[data-category=""]').click()
    page.get_by_label("Категорія листа", exact=True).select_option("Навчання")
    page.get_by_role("button", name="Зберегти цей лист в Outlook").click()
    page.locator("#detail .tag").filter(has_text="Навчання").wait_for()
    page.locator("#profile-nav").click()
    assert page.locator("#teams-connect").is_visible()
    page.set_viewport_size({"width": 600, "height": 900})
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert not errors, errors
    browser.close()
    print(
        "Browser smoke passed: profile, preferences, timer, pause, manual categorization, text safety, responsive layout."
    )
