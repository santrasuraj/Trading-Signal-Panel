"""Quant Desk API: JSON under /api, and the built React app (web/ui/dist) for everything else.

Run:  python -m web.serve   (or double-click 3_dashboard.bat). Binds to 127.0.0.1 only.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from scanner.daily import load_latest

DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"

app = FastAPI(title="Quant Desk API", version="3.0", docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/latest")
def latest() -> dict:
    r = load_latest()
    if r is None:
        raise HTTPException(404, "No scan yet - run a scan first")
    return r


# ---- the React single-page app (must be registered last) -----------------------------------
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    f = DIST / path
    if path and f.is_file():
        return FileResponse(f)
    index = DIST / "index.html"
    if not index.exists():
        raise HTTPException(503, "Frontend not built yet: run `npm run build` in web/ui")
    return FileResponse(index)
