"""Verify stale-plan UI against fictional responses; no user data is accessed."""

import os
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        executable_path=os.getenv("CHROMIUM_PATH", "/usr/bin/chromium"),
        args=["--no-sandbox"],
    )
    page = browser.new_page()
    failures = []
    page.on("pageerror", lambda e: failures.append(str(e)))
    unavailable = False

    def route(r):
        path = r.request.url.split("/api/")[1]
        if path == "status":
            data = {
                "connected": True,
                "desktop": True,
                "csrf": "fixture",
                "profile": {"email": "person@example.com"},
                "teams": {"status": "disconnected"},
            }
        elif path == "messages":
            data = {"messages": [], "limited": False}
        elif path == "meetings":
            data = {"results": {}}
        elif path == "plan":
            if unavailable:
                r.fulfill(
                    status=503, json={"error": "Calendar unavailable (fictional)"}
                )
                return
            data = {
                "sources": {},
                "meetings": [],
                "backlog": [],
                "blocks": [
                    {
                        "id": "task",
                        "title": "Preserved task",
                        "source": "Jira",
                        "start": "2026-11-02T10:00:00+02:00",
                        "end": "2026-11-02T11:00:00+02:00",
                    }
                ],
            }
        else:
            data = {"ok": True}
        r.fulfill(json=data)

    page.route("**/api/**", route)
    page.goto(os.getenv("WA_TEST_URL", "http://127.0.0.1:8008"))
    page.locator("#notice").filter(has_text="Запрошення перевірено").wait_for()
    page.locator("#plan-nav").click()
    page.get_by_text("Preserved task", exact=True).wait_for()
    unavailable = True
    page.locator("#refresh").click()
    page.locator("#plan-sources").filter(has_text="дані застаріли").wait_for()
    assert page.get_by_text("Preserved task", exact=True).is_visible()
    page.locator('[data-category=""]').click()
    page.locator("#plan-nav").click()
    assert "попередній графік" in page.locator("#plan-sources").inner_text()
    assert not failures, failures
    browser.close()
    print(
        "Resilience passed: previous plan retained and stale warning survives navigation."
    )
