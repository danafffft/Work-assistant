"""Run the local application in a native Windows window."""

import os
import threading
from http.server import ThreadingHTTPServer
import app


def main():
    if os.name != "nt":
        raise SystemExit("Для підключення потрібні Windows і класичний Outlook.")
    import ctypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    mutex = kernel.CreateMutexW(None, False, "Local\\WorkAssistantDesktop")
    if not mutex:
        raise RuntimeError("Не вдалося створити локальний сеанс застосунку.")
    if ctypes.get_last_error() == 183:
        from tkinter import messagebox

        messagebox.showinfo(
            "Work Assistant",
            "Застосунок уже відкритий. Перевірте панель завдань Windows.",
        )
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel.CloseHandle(mutex)
        return
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
        kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        from tkinter import messagebox

        messagebox.showerror(
            "Work Assistant",
            "Не вдалося відкрити застосунок. Переконайтеся, що встановлено Edge WebView2. Для версії з вихідного коду запустіть Start-WorkAssistant.bat; для інсталятора зверніться до видавця збірки.",
        )
