"""Start the Quant Desk server on http://127.0.0.1:8600 and open the browser."""
from __future__ import annotations

import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402

HOST, PORT = "127.0.0.1", 8600

if __name__ == "__main__":
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    uvicorn.run("web.api.main:app", host=HOST, port=PORT, log_level="warning", reload="--reload" in sys.argv)
