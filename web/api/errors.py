"""The error envelope {"error": {code, message, hint, details}} and a NaN-safe JSON response."""
from __future__ import annotations

import json
import logging
import math
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .paths import P

STATUS = {"NO_SCAN": 404, "NOT_FOUND": 404, "VALIDATION": 422, "SCAN_BUSY": 409, "FYERS_NOT_CONFIGURED": 409,
          "FYERS_LOGIN_REQUIRED": 409, "FYERS_AUTH": 502, "FYERS_RATE_LIMIT": 429, "FEATURE_UNAVAILABLE": 501,
          "CSRF": 403, "FORBIDDEN_HOST": 403, "INTERNAL": 500}

log = logging.getLogger("quantdesk.api")


class _ApiLog(RotatingFileHandler):
    """api.log, opened (and its folder created) only when the first record is written."""

    def _open(self):
        Path(self.baseFilename).parent.mkdir(parents=True, exist_ok=True)
        return super()._open()


def setup_logging() -> None:
    """Attach api.log under P.logs; called again by paths.configure(), which moves it with the data folder
    (otherwise the handler made at import keeps writing into the real data/logs, e.g. during tests)."""
    target = os.path.abspath(P.logs / "api.log")         # the same normalisation FileHandler applies
    for h in list(log.handlers):
        if isinstance(h, _ApiLog):
            if h.baseFilename == target:
                return
            log.removeHandler(h)
            h.close()
    try:
        h = _ApiLog(target, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    except OSError:
        pass


class ApiException(Exception):
    def __init__(self, code: str, message: str, hint: str | None = None, details: dict | None = None,
                 status: int | None = None):
        super().__init__(message)
        self.code, self.message, self.hint, self.details = code, message, hint, details
        self.status = status or STATUS.get(code, 500)


def no_scan() -> ApiException:
    return ApiException("NO_SCAN", "No scan results yet.", "Run a scan (top bar > Scan) - the first one takes a few minutes.")


def not_found(what: str, hint: str | None = None) -> ApiException:
    return ApiException("NOT_FOUND", f"{what} not found.", hint)


def feature_unavailable(feature: str, message: str, hint: str | None = None) -> ApiException:
    return ApiException("FEATURE_UNAVAILABLE", message, hint, {"feature": feature})


def _clean(v: Any) -> Any:
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


class SafeJSONResponse(JSONResponse):
    """JSON with NaN/inf -> null (the stdlib encoder would raise). Fast path for clean payloads."""

    def render(self, content: Any) -> bytes:
        try:
            text = json.dumps(content, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except ValueError:
            text = json.dumps(_clean(content), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        return text.encode("utf-8")


def envelope(code: str, message: str, hint: str | None = None, details: dict | None = None,
             status: int | None = None) -> SafeJSONResponse:
    return SafeJSONResponse({"error": {"code": code, "message": message, "hint": hint, "details": details}},
                            status_code=status or STATUS.get(code, 500), headers={"Cache-Control": "no-store"})


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiException)
    async def _api(_: Request, e: ApiException):
        return envelope(e.code, e.message, e.hint, e.details, e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        errs = [{"loc": [str(x) for x in err.get("loc", [])], "msg": str(err.get("msg", "")),
                 "type": str(err.get("type", ""))} for err in e.errors()]
        first = errs[0] if errs else {"loc": [], "msg": "invalid request", "type": ""}
        if first.get("type") == "json_invalid":      # its loc is ['body', <char offset>]: not a field name
            return envelope("VALIDATION", "Invalid request: the body is not valid JSON.",
                            "Send a JSON object, e.g. {\"rows\": [...]}.", {"errors": errs})
        where = ".".join(x for x in first["loc"] if x not in ("body", "query", "path"))
        return envelope("VALIDATION", f"Invalid request: {where + ': ' if where else ''}{first['msg']}",
                        None, {"errors": errs})

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "VALIDATION", 422: "VALIDATION", 403: "CSRF"}.get(e.status_code, "INTERNAL")
        msg = e.detail if isinstance(e.detail, str) else "Request failed."
        return envelope(code, msg, status=e.status_code)

    @app.exception_handler(Exception)
    async def _internal(request: Request, e: Exception):
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return envelope("INTERNAL", f"Internal error: {type(e).__name__}: {e}"[:300],
                        "Details are in data/logs/api.log.")
