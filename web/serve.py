"""Start the Quant Desk server on http://127.0.0.1:8600 and open the browser.

  python -m web.serve               the server (3_dashboard.bat adds --reload)
  python -m web.serve --reload      the server restarts by itself when the app's Python code changes (an update,
                                    a git pull), so an open Quant Desk never keeps serving yesterday's code
  --no-browser                      don't open the browser
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

HOST, PORT = "127.0.0.1", 8600
# Only the app's own code is watched: the whole folder would mean scanning .venv and node_modules (thousands of files).
WATCH_DIRS = [ROOT / "web" / "api", ROOT / "scanner"]
WATCH_EVERY_S = 2.0


def code_snapshot() -> dict[str, float]:
    """Every watched .py file and its modification time."""
    out: dict[str, float] = {}
    for d in WATCH_DIRS:
        for p in d.rglob("*.py"):
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                pass
    return out


def serve_with_reload() -> int:
    """Run the server as a child process and replace it when the code changes. A hard stop of the child is safe here:
    every file the app writes is written atomically, and scans / intraday jobs run as their own processes, which go
    on. (uvicorn's own --reload stops its worker with Ctrl+C, which a Windows process without a console never gets:
    the old code then kept running.)"""
    args = [sys.executable, "-m", "uvicorn", "web.api.main:app", "--host", HOST, "--port", str(PORT),
            "--log-level", "warning"]
    while True:
        snap = code_snapshot()
        child = subprocess.Popen(args, cwd=str(ROOT))
        try:
            while child.poll() is None:
                time.sleep(WATCH_EVERY_S)
                if code_snapshot() != snap:
                    print("Quant Desk was updated - restarting the server...", flush=True)
                    child.terminate()
                    try:
                        child.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
                    break
            else:
                return child.returncode or 0          # the server stopped by itself (e.g. the port is taken)
        except KeyboardInterrupt:
            child.terminate()
            return 0


if __name__ == "__main__":
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    if "--reload" in sys.argv:
        sys.exit(serve_with_reload())
    uvicorn.run("web.api.main:app", host=HOST, port=PORT, log_level="warning")
