"""Launch the local web UI and open it in your browser.

    python scripts/run_ui.py

Runs a local-only server (http://127.0.0.1:5000) — nothing is exposed to the
internet. Press Ctrl+C in the terminal to stop it.
"""

from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HOST = "127.0.0.1"
PORT = 5000


def _already_running(host: str, port: int) -> bool:
    """Is a Job Finder already listening on this port?

    We have to check by hand. Windows lets a second server bind a port that is
    already in use (the socket sets SO_REUSEADDR), so starting the app twice
    does NOT fail: you end up with two servers on 5000 and the browser talking
    to whichever one happens to catch each connection. When one of them is
    running older code, the page misbehaves in ways that look impossible.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.6)
        return probe.connect_ex((host, port)) == 0


def main() -> int:
    url = f"http://{HOST}:{PORT}"

    # Never start a second server on top of a running one (see above).
    if _already_running(HOST, PORT):
        print("Job Finder is already running in another window.")
        print("Opening that one in your browser instead of starting a second copy.")
        print()
        print("If the app is behaving oddly, close EVERY Job Finder window,")
        print("wait a couple of seconds, then start it again.")
        webbrowser.open(url)
        return 0

    try:
        from webapp.app import app
    except Exception as exc:
        print("Could not start the UI:", exc)
        print("Make sure you're using the venv Python and ran: pip install -r requirements.txt")
        return 1

    print(f"Job Hunting Agent UI running at {url}")
    print("Opening your browser… (press Ctrl+C here to stop)")

    # Open the browser shortly after the server starts.
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    # use_reloader=False so we don't spawn a second process / open twice.
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
