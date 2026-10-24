"""Local-only, but browsers are hostile.

- Host guard (DNS rebinding): only Host 127.0.0.1 / localhost (any port) is served; otherwise 403
  FORBIDDEN_HOST in the normal error envelope.
- Mutation guard (CSRF): every non-GET/HEAD/OPTIONS request under /api must carry `X-Quant-Desk: 1`.
  There is no CORS middleware, so another origin cannot add a custom header without a preflight that fails.
  As a second layer, such a request whose Origin is another site (or 'null') is refused too (403 CSRF).
- Cache-Control: no-store on /api/*.
"""
from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from .errors import envelope

ALLOWED_HOSTS = {"127.0.0.1", "localhost"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
GUARD_HEADER = b"x-quant-desk"


def _hostname(host: str) -> str:
    host = host.strip().lower()
    if host.startswith("["):                      # [::1]:8600
        return host[: host.find("]") + 1]
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class SecurityMiddleware:
    """Pure ASGI middleware (no BaseHTTPMiddleware overhead, works with streaming responses)."""

    def __init__(self, app: ASGIApp, allowed_hosts: set[str] | None = None):
        self.app = app
        self.allowed = set(allowed_hosts or ALLOWED_HOSTS)

    def _own_origin(self, origin: bytes | None) -> bool:
        """No Origin (scripts, curl) or an http(s) origin on an allowed host (any port, e.g. the Vite dev server).
        Defence in depth behind the guard header: 'null' (sandboxed frame, file://) and other sites are refused."""
        if origin is None:
            return True
        scheme, sep, rest = origin.decode("latin-1").strip().lower().partition("://")
        return bool(sep) and scheme in ("http", "https") and _hostname(rest.split("/", 1)[0]) in self.allowed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope.get("headers") or []}
        host = _hostname(headers.get(b"host", b"").decode("latin-1"))
        if host not in self.allowed:
            await envelope("FORBIDDEN_HOST", "This server only answers requests for 127.0.0.1 or localhost.",
                           "Open http://127.0.0.1:8600 instead.")(scope, receive, send)
            return
        path = scope.get("path", "")
        is_api = path == "/api" or path.startswith("/api/")
        mutating = is_api and scope.get("method", "GET") not in SAFE_METHODS
        if mutating and headers.get(GUARD_HEADER) != b"1":
            await envelope("CSRF", "Missing X-Quant-Desk: 1 header on a state-changing request.",
                           "The Quant Desk UI adds it automatically; scripts must send it too.")(scope, receive, send)
            return
        if mutating and not self._own_origin(headers.get(b"origin")):
            await envelope("CSRF", "State-changing requests are only accepted from the Quant Desk page itself.",
                           "Open http://127.0.0.1:8600 instead.")(scope, receive, send)
            return
        if not is_api:
            await self.app(scope, receive, send)
            return

        async def send_no_store(message):
            if message["type"] == "http.response.start":
                hs = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                hs.append((b"cache-control", b"no-store"))
                message = {**message, "headers": hs}
            await send(message)

        await self.app(scope, receive, send_no_store)
