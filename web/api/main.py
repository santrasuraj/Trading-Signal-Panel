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
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles

from . import errors
from .errors import ApiException, SafeJSONResponse
from .routers import lookup, market, ops, overview, portfolio, smart_money, strategies, system
from .security import SecurityMiddleware

DIST = Path(__file__).resolve().parent.parent / "ui" / "dist"
OPENAPI_FILE = Path(__file__).resolve().parent / "openapi.json"


def warm_up(app: FastAPI | None = None) -> None:
    """Load the slow first-time caches in the background, so the first overview / strategies / chart after a start
    is fast. Ordered by what the first page load needs: the paper report (~2 s, used by overview, strategies and
    signals) right after the files it is built from, then the results calendar and index history; market
    statistics after; the OpenAPI schema (4-6 s of CPU, only /api/docs uses it) last."""
    from .services import data, market_derived, paper_svc
    steps = [data.latest, data.curves, data.store, paper_svc.report, data.symbol_meta, data.results_events,
             data.index_history, market_derived.factors, lambda: market_derived.breadth("1y"),
             market_derived.industries, data._past_results_index]
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
    for r in (system, overview, strategies, lookup, portfolio, market, ops, smart_money):
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

    # ---- the React single-page app (registered last) ------------------------------------------------
    if (DIST / "assets").exists():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    # The app shell must be revalidated on every load: a heuristically cached index.html would keep asking for
    # the hashed /assets of an older build, which a rebuild deleted (blank app until a hard refresh).
    no_cache = {"Cache-Control": "no-cache"}

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        root = DIST.resolve()
        index = root / "index.html"
        if path:
            try:
                f = (root / path).resolve()
            except (OSError, ValueError):
                f = None
            # path-traversal guard: only files inside web/ui/dist are ever served
            if f is not None and f.is_relative_to(root) and f.is_file():
                return FileResponse(f, headers=no_cache if f == index else None)
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
