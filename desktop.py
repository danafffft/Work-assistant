"""Run the local application in a native Windows window."""

import os
import threading
from http.server import ThreadingHTTPServer
import app


def main():
    if os.name != "nt":
        raise SystemExit("Для підключення потрібні Windows і класичний Outlook.")
    import webview

    server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webview.create_window(
        "Work Assistant",
        f"http://127.0.0.1:{port}",
        width=1440,
        height=940,
        min_size=(960, 680),
    )
    try:
        webview.start()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
