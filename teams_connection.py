"""User-approved Microsoft device sign-in; tokens remain in session memory."""

import threading
import time
import urllib.parse


def start(session, client_id, email=""):
    if not client_id:
        raise ValueError(
            "Потрібен Application (client) ID, дозволений вашим IT для Teams."
        )
    if session.get("teams", {}).get("status") == "pending":
        return public_status(session)
    import msal

    client = msal.PublicClientApplication(
        client_id, authority="https://login.microsoftonline.com/organizations"
    )
    flow = client.initiate_device_flow(scopes=["User.Read", "Chat.Read"])
    if "user_code" not in flow:
        raise ValueError(
            "Microsoft не дозволив почати вхід. Перевірте client ID та політики організації."
        )
    state = {
        "status": "pending",
        "code": flow["user_code"],
        "url": flow["verification_uri"],
        "expires": time.time() + flow["expires_in"],
    }
    session["teams"] = state

    def finish():
        try:
            result = client.acquire_token_by_device_flow(flow)
            if session.get("teams") is not state:
                return
            if "access_token" in result:
                state.update(
                    status="connected",
                    token=result["access_token"],
                    expires=time.time() + result.get("expires_in", 3600),
                )
                session.pop("sourceCache", None)
            else:
                state.update(status="error")
        except Exception:
            state.update(status="error")
        finally:
            state.pop("code", None)

    threading.Thread(target=finish, daemon=True).start()
    return public_status(session)


def public_status(session):
    state = session.get("teams", {})
    status = state.get("status", "disconnected")
    if state.get("expires", 0) <= time.time() and status in ("pending", "connected"):
        status = "expired"
    result = {"status": status}
    if status == "pending":
        result.update(code=state["code"], url=state["url"])
    return result


def tasks(session, request):
    from integrations import mentioned_tasks

    state = session.get("teams", {})
    if public_status(session)["status"] != "connected":
        return (
            [],
            "Teams не підключено. Увійдіть у профілі та надайте дозволений доступ.",
        )

    def graph(path):
        return request("https://graph.microsoft.com/v1.0" + path, token=state["token"])

    me = graph("/me?$select=id")
    chats = graph("/me/chats?$top=50")
    result = []
    for chat in chats.get("value", []):
        data = graph(
            "/chats/" + urllib.parse.quote(chat["id"], safe="") + "/messages?$top=50"
        )
        result.extend(mentioned_tasks(data.get("value", []), me["id"], chat["id"]))
    return (
        result,
        "Teams: до 50 останніх повідомлень у 50 чатах. Згадки — кандидати задач по 30 хв; канали не скануються.",
    )
