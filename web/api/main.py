"""Quant Desk API: JSON under /api, and the built React app (web/ui/dist) for everything else.

Run:  python -m web.serve   (or double-click 3_dashboard.bat). Binds to 127.0.0.1 only.
Contract: docs/ui_spec.md amended by docs/ui_spec_review.md ("Final API contract"); the pydantic models in
web/api/models are its source of truth and web/api/openapi.json is generated from them
(python -m web.api.main --openapi).

GET handlers never touch the network: they read latest.json and the other result files, the price store and
the NSE caches. Only explicit POSTs (scan, intraday run, Fyers login, Fyers holdings import) start network work.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.routing import APIRoute

from . import errors
from .errors import ApiException, SafeJSONResponse
from .routers import (action, ai, builder, coach, desk, fno, levels, lookup, market, ops, options, outlook, overview, portfolio, smart_money,
                      orders, replay, research, scans, sim, strategies, stream, system, views, watch)
from .security import SecurityMiddleware
from .services import fyers_svc

DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
OPENAPI_FILE = Path(__file__).resolve().parent / "openapi.json"

# One segment of a path under web/ui/dist: Vite's file names (index-Be40HyvD.js, inter-latin-wght-normal-x.woff2).
# No backslash, colon, empty segment or leading dot, so no "..", no drive letter and no \\host\share UNC path.
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._@+~-]*")


def dist_file(root: Path, path: str) -> Path | None:
    """The file under `root` (web/ui/dist) that the URL path names, or None. The path is checked as text BEFORE
    the filesystem sees it: on Windows, resolving `\\\\host\\share\\x` (the URL /%5C%5Chost%5Cshare%5Cx) or
    `//host/share` opens an SMB connection that sends the user's NTLM hash to that host, before any
    is_relative_to check could reject it."""
    parts = path.split("/")
    if not all(_SAFE_SEGMENT.fullmatch(p) for p in parts):
        return None
    f = root.joinpath(*parts)
    try:
        if not f.is_file():
            return None
        f = f.resolve()
    except (OSError, ValueError):
        return None
    return f if f.is_relative_to(root) else None      # a symlink inside dist must not lead out of it


def warm_up(app: FastAPI | None = None) -> None:
    """Load the slow first-time caches in the background, so the first overview / strategies / chart after a start
    is fast. Ordered by what the first page load needs: the paper report (~2 s, used by overview, strategies and
    signals) right after the files it is built from, then the results calendar and index history; market
    statistics after; then big money's 30- and 90-day views (~15 s cold, mostly reading its files: the Smart Money
    pages and big money live read them); the OpenAPI schema (4-6 s of CPU, only /api/docs uses it) last."""
    from .services import data, market_derived, paper_svc, smart_money_svc
    steps = [data.latest, data.curves, data.store, paper_svc.report, data.symbol_meta, data.results_events,
             data.index_history, market_derived.factors, lambda: market_derived.breadth("1y"),
             market_derived.industries, data._past_results_index, lambda: smart_money_svc._derived(30),
             lambda: smart_money_svc._derived(90)]
    from .services import late_entry_svc
    steps.append(lambda: late_entry_svc.report(wait=True))     # late-entry BUYs on Today (~10 s, the 8-year panel)
    if app is not None:
        steps.append(app.openapi)
    for step in steps:
        try:
            step()
        except Exception:
            errors.log.exception("warm-up step failed")


def create_app(warm: bool = True) -> FastAPI:
    errors.setup_logging()

    @asynccontextmanager
    async def lifespan(_app):
        if warm:
            threading.Thread(target=warm_up, args=(_app,), name="warm-up", daemon=True).start()
        yield

    app = FastAPI(title="Quant Desk API", version=system.VERSION, docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json", default_response_class=SafeJSONResponse, lifespan=lifespan)
    app.add_middleware(SecurityMiddleware)
    errors.install(app)
    for r in (system, overview, strategies, lookup, portfolio, market, ops, smart_money, options, fno, levels, outlook, ai,
              action, watch, scans, research, orders, replay, coach, sim, builder, views, desk, stream):
        app.include_router(r.router)

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    def api_not_found(rest: str, request: Request):
        # this catch-all also receives a known path with the wrong method (e.g. DELETE /api/holdings): that is a 405
        path = f"/api/{rest}"
        allowed = sorted({m for r in app.routes if isinstance(r, APIRoute) and r.path != "/api/{rest:path}"
                          and r.path.startswith("/api/") and r.path_regex.match(path) for m in r.methods})
        if allowed:
            raise ApiException("VALIDATION", f"{request.method} is not allowed on {path}.", f"Use {' or '.join(allowed)}.",
                               {"allowed": allowed}, status=405)
        raise ApiException("NOT_FOUND", f"No API endpoint /api/{rest}.", "See /api/docs for the endpoint list.")

    # ---- Fyers' redirect after a one-click login (registered before the SPA catch-all) ---------------------------
    # A page, not JSON: it is the tab the user lands on. It finishes only a login started here (its random state),
    # so a link from another site can't log the app into someone else's account (fyers_svc.callback_page).
    @app.get(fyers_svc.CALLBACK_PATH, include_in_schema=False)
    def fyers_callback(request: Request):
        status_code, page = fyers_svc.callback_page(parse_qs(request.url.query))
        return HTMLResponse(page, status_code=status_code, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    # ---- the React single-page app (registered last) ------------------------------------------------
    # No StaticFiles mount for /assets: it resolves the path on disk before its own containment check (the
    # same UNC problem as dist_file's docstring), so every file, /assets included, goes through dist_file.

    # The app shell must be revalidated on every load: a heuristically cached index.html would keep asking for
    # the hashed /assets of an older build, which a rebuild deleted (blank app until a hard refresh).
    no_cache = {"Cache-Control": "no-cache"}
    # Vite puts a content hash in every /assets file name, so a name never changes meaning
    immutable = {"Cache-Control": "public, max-age=31536000, immutable"}

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        root = DIST.resolve()
        index = root / "index.html"
        if path:
            # path-traversal guard: only files inside web/ui/dist are ever served
            f = dist_file(root, path)
            if f is not None:
                headers = no_cache if f == index else immutable if path.startswith("assets/") else None
                return FileResponse(f, headers=headers)
            if path.startswith("assets/"):     # a missing script must not get index.html (a MIME error, not a 404)
                raise ApiException("NOT_FOUND", "Asset not found.", "Reload the page: the app was rebuilt.")
        if not index.exists():
            raise ApiException("FEATURE_UNAVAILABLE", "Frontend not built yet: run `npm ci && npm run build` in web/ui.",
                               "3_dashboard.bat builds it automatically.", {"feature": "ui"})
        return FileResponse(index, headers=no_cache)

    return app


app = create_app()


def write_openapi(path: Path = OPENAPI_FILE) -> Path:
    spec = create_app(warm=False).openapi()
    path.write_text(json.dumps(spec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    if "--openapi" in sys.argv:
        print(write_openapi())
