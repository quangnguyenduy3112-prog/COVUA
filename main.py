from __future__ import annotations

import threading
import webbrowser

import uvicorn

if __name__ == "__main__":
    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:8765")).start()
    uvicorn.run("app.server:app", host="127.0.0.1", port=8765, log_level="info")
