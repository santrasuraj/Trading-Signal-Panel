"""Fyers status (file reads only unless verify=true) and the login flows.

One-click ("direct") login: the app makes the Fyers login link with a random `state`, the browser opens Fyers in a
new tab, and Fyers sends the browser back to the app's Redirect URL with an auth code. Who receives it depends on that
URL (`capture_mode`):

  app       the Redirect URL is Quant Desk's own http://127.0.0.1:8600/fyers/callback: the server finishes the login
            itself (the best setup; Settings > Fyers sets .env for it once the Fyers app uses it)
  listener  another local address whose port is free: a one-shot listener catches it there for 10 minutes
  paste     the port is taken (e.g. Docker on 8000 receives it): the user pastes the address bar (the old flow)

A callback or listener request is accepted only with the `state` of a login started here in the last 10 minutes,
once: a link from another site can't log this app into someone else's Fyers account.
Never returned: .env values, the access token, the secret. The client id is masked (ABCD****-100).
Token file format = login.py's {client_id, access_token, created}.
"""
from __future__ import annotations

import html
import json
import os
import secrets
import socket
import subprocess
import threading
import time
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

from scanner import providers
from scanner.fyers_limits import FyersRateLimited
from scanner.lock import running_scan
from scanner.settings import env

from . import data
from ..errors import ApiException
from ..paths import P
from ..util import now_ist

DEFAULT_REDIRECT = "http://127.0.0.1:8000/api/v1/auth/callback"   # login.DEFAULT_REDIRECT
APP_PORT = 8600                                                    # web/serve.py PORT
CALLBACK_PATH = "/fyers/callback"
APP_CALLBACK = f"http://127.0.0.1:{APP_PORT}{CALLBACK_PATH}"
LOCAL_HOSTS = ("127.0.0.1", "localhost")
VERIFY_TTL = 300
SESSION_TTL = 600

_lock = threading.Lock()
_verify: dict = {"key": None, "at": 0.0, "ok": None, "name": None, "when": None}
_pending: dict = {"session": None, "state": None, "expires": 0.0}
_listener: dict = {"server": None, "stop": None, "thread": None}


def _mask(cid: str) -> str | None:
    if not cid:
        return None
    head, _, tail = cid.partition("-")
    return f"{head[:4]}****{'-' + tail if tail else ''}"


def token() -> dict | None:
    try:
        tok = json.loads(P.token.read_text(encoding="utf-8"))
        return tok if tok.get("access_token") and tok.get("client_id") else None
    except Exception:
        return None


def status(verify: bool = False, lt: dict | None = None) -> dict:
    cfg = data.config()
    cid, secret = env("FYERS_CLIENT_ID"), env("FYERS_SECRET_KEY")
    tok = token()
    created = tok.get("created") if tok else None
    # the scanner's own rule (providers.token_expired): a token made before the latest 06:00 IST is dead
    today_tok = bool(tok and created and not providers.token_expired(tok))
    plan = "prime" if str(cfg.get("fyers_plan", "standard")).lower() == "prime" else "standard"
    source = "yahoo" if str(cfg.get("data_source", "auto")).lower() == "yahoo" else "auto"
    redirect = env("FYERS_REDIRECT_URI", DEFAULT_REDIRECT)
    out = {"configured": bool(cid and secret), "client_id_masked": _mask(cid), "plan": plan, "data_source": source,
           "token_present": tok is not None, "token_created": created, "logged_in_today": today_tok,
           "verified": None, "verified_at": None, "user_name": None,
           "redirect_uri": redirect, "login_modes": ["direct", "paste", "window"],
           "direct_mode": capture_mode(redirect), "callback_url": APP_CALLBACK}
    if verify and tok:
        _do_verify(tok, plan)
    if tok and _verify["key"] == tok.get("access_token", "")[-12:]:
        out.update(verified=_verify["ok"], verified_at=_verify["when"], user_name=_verify["name"])
    lt = lt if lt is not None else data.latest()
    if source == "yahoo":
        note = "Fyers disabled in config.yaml (data_source: yahoo) - live prices from Yahoo (~15 min delayed)."
    elif not out["configured"]:
        note = "Fyers app not configured: add FYERS_CLIENT_ID and FYERS_SECRET_KEY to .env (see README)."
    elif not today_tok:
        note = "Not logged in to Fyers today - live prices from Yahoo (~15 min delayed). Log in once each morning."
    elif _protected(plan):
        # get_fyers() falls back to Yahoo in this case: say so instead of promising real-time prices
        note = "FYERS rate-limit protection is active today - live prices from Yahoo (~15 min delayed) until tomorrow."
    elif out["verified"] is False:
        note = "Today's Fyers token was rejected - log in again."
    else:
        note = "Logged in to Fyers today - real-time prices for the next scan."
    out["note"] = note
    return out


def _protected(plan: str) -> bool:
    """FYERS rate-limit protection is on for today (same test as providers.get_fyers; a file read only)."""
    use = providers.FyersLimiter(plan).usage()       # never raises
    return bool(use["stopped"] or use["data"]["remaining_today"] <= 0)


def _profile(p) -> tuple[bool | None, str | None]:
    """One get_profile call through the shared limiter: (True, name) = token works, (False, None) = Fyers
    rejected the token, (None, None) = unknown - rate-limit protection, a busy usage file, a network error or
    any other FYERS error says nothing about the token (check_login() would report all of these as rejected)."""
    try:
        r = p._call(p.api.get_profile, bucket="user")
    except providers.FyersAuthError:
        return False, None
    except FyersRateLimited:
        return None, None
    if r.get("s") == "ok":
        return True, (r.get("data") or {}).get("name") or None
    return None, None


def _do_verify(tok: dict, plan: str) -> None:
    """One get_profile call, cached 5 minutes, never while a scan runs (its throttle owns the budget)."""
    key = tok.get("access_token", "")[-12:]
    with _lock:
        if _verify["key"] == key and time.monotonic() - _verify["at"] < VERIFY_TTL:
            return
        if running_scan():
            return
        use = providers.FyersLimiter(plan).usage()       # file read only, never raises
        if use["stopped"] or use["user"]["remaining_today"] <= 0:
            return   # FYERS rate-limit protection: a refused profile call must not read as "token rejected"
        try:
            ok, name = _profile(providers.FyersProvider(tok["client_id"], tok["access_token"], plan=plan))
        except Exception:       # SDK import / log folder problems: unknown, not "rejected"
            ok, name = None, None
        _verify.update(key=key, at=time.monotonic(), ok=ok, name=name if ok else None,
                       when=now_ist().isoformat(timespec="seconds"))


def _credentials() -> tuple[str, str, str]:
    cid, secret = env("FYERS_CLIENT_ID"), env("FYERS_SECRET_KEY")
    if not cid or not secret:
        raise ApiException("FYERS_NOT_CONFIGURED", "FYERS_CLIENT_ID / FYERS_SECRET_KEY are missing in .env.",
                           "Copy .env.example to .env and fill them in (README, step 2), then restart Quant Desk.")
    return cid, secret, env("FYERS_REDIRECT_URI", DEFAULT_REDIRECT)


def _port_free(host: str, port: int) -> bool:
    """Whether this app could listen on host:port now. Exclusive bind on Windows: a plain bind (SO_REUSEADDR) can
    succeed on a port another program (Docker / WSL on 8000) listens on, and that program would get the redirect."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("127.0.0.1" if host == "localhost" else host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def capture_mode(redirect: str) -> str:
    """Who receives Fyers' redirect: 'app' (this server's callback), 'listener' (a free local port) or 'paste'."""
    u = urlparse(redirect or "")
    if u.scheme != "http" or u.hostname not in LOCAL_HOSTS:
        return "paste"
    port = u.port or 80
    if port == APP_PORT:
        return "app" if u.path.rstrip("/") == CALLBACK_PATH else "paste"   # another path here goes to the SPA
    return "listener" if _port_free(u.hostname, port) else "paste"


def login(mode: str) -> dict:
    if mode == "window":
        if not P.login_bat.exists():
            raise ApiException("INTERNAL", "1_login.bat not found next to the app.")
        if os.name == "nt":
            subprocess.Popen(["cmd", "/c", str(P.login_bat)], cwd=str(P.root),
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:  # pragma: no cover - Windows app
            subprocess.Popen(["python", str(P.root / "login.py")], cwd=str(P.root))
        return {"mode": "window", "login_url": None, "expires_at": None,
                "instructions": ["A login window and the Fyers page are opening.",
                                 "Follow the steps in that window; this page updates when the token is saved."]}
    cid, secret, redirect = _credentials()
    from fyers_apiv3 import fyersModel
    state = secrets.token_urlsafe(16)
    session = fyersModel.SessionModel(client_id=cid, secret_key=secret, redirect_uri=redirect,
                                      response_type="code", grant_type="authorization_code", state=state)
    url = session.generate_authcode()
    with _lock:
        _pending.update(session=session, state=state, expires=time.monotonic() + SESSION_TTL)
    expires = (now_ist() + timedelta(seconds=SESSION_TTL)).isoformat(timespec="seconds")
    capture = capture_mode(redirect) if mode == "direct" else "paste"
    if capture == "listener" and not _start_listener(redirect):
        capture = "paste"
    if capture in ("app", "listener"):
        return {"mode": "direct", "capture": capture, "login_url": url, "expires_at": expires,
                "instructions": ["Log in on the Fyers page that opened in a new tab.",
                                 "That is all: this page updates by itself when Fyers sends you back.",
                                 "The login link expires in 10 minutes."]}
    return {"mode": "paste", "capture": "paste", "login_url": url, "expires_at": expires,
            "instructions": ["Log in on the Fyers page that opened in a new tab.",
                             "Afterwards the browser may show an error or another app's page - that is fine.",
                             "Copy the FULL address from the address bar (it contains 'auth_code=') and paste it here.",
                             "The login link expires in 10 minutes."]}


# --------------------------------------------------------------------------- receiving Fyers' redirect
def _page(ok: bool, title: str, detail: str | None) -> str:
    """The small page the Fyers tab lands on (escaped text; it tries to close itself after a success)."""
    color = "#15803d" if ok else "#b91c1c"
    mark = "&#10003;" if ok else "&#10007;"
    close = "<script>setTimeout(function(){window.close()},1500)</script>" if ok else ""
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
        "content='width=device-width,initial-scale=1'><title>Fyers login - Quant Desk</title></head>"
        "<body style='margin:0;font-family:Inter,system-ui,sans-serif;background:#f6f7f9;color:#111827'>"
        "<div style='max-width:420px;margin:12vh auto;padding:28px;background:#fff;border:1px solid #e5e7eb;"
        "border-radius:12px;text-align:center'>"
        f"<div style='font-size:34px;color:{color}'>{mark}</div>"
        f"<h1 style='font-size:18px;margin:8px 0'>{html.escape(title)}</h1>"
        + (f"<p style='font-size:14px;color:#4b5563;margin:0 0 18px'>{html.escape(detail)}</p>" if detail else "")
        + f"<a href='http://127.0.0.1:{APP_PORT}/' style='display:inline-block;padding:8px 14px;border-radius:8px;"
        "background:#2563eb;color:#fff;text-decoration:none;font-size:14px'>Open Quant Desk</a>"
        f"</div>{close}</body></html>")


def callback_page(q: dict) -> tuple[int, str]:
    """(HTTP status, page) for Fyers' redirect, here (/fyers/callback) or on the listener. Needs the `state` of the
    login started here: a forged link can't log the app into another account."""
    code = (q.get("auth_code") or [None])[0]
    state = (q.get("state") or [None])[0]
    if not code:
        msg = (q.get("message") or q.get("msg") or [None])[0]
        return 400, _page(False, "Fyers did not send a login code" + (f": {msg}" if msg else "."),
                          "Start the login again from Quant Desk.")
    try:
        r = _finish(code, state, need_state=True)
    except ApiException as e:
        return 400, _page(False, e.message, e.hint)
    if not r["ok"]:
        return 200, _page(False, "Fyers did not confirm the login.",
                          "Start the login again; if it keeps failing, check the App ID and Secret in .env.")
    who = f" as {r['user_name']}" if r.get("user_name") else ""
    return 200, _page(True, f"Logged in to Fyers{who}.", "You can close this tab: Quant Desk has already updated.")


def _stop_listener() -> None:
    old = _listener.get("server")
    if old is not None:
        _listener["stop"].set()
        _listener["thread"].join(timeout=3)


def _start_listener(redirect: str) -> bool:
    """A one-shot web server on the Redirect URL's local port for this login (10 minutes at most); False when the
    port can't be had, so the paste flow takes over at once."""
    u = urlparse(redirect)
    path = (u.path or "/").rstrip("/") or "/"
    _stop_listener()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):                                         # noqa: N802 - http.server API
            url = urlparse(self.path)
            if ((url.path or "/").rstrip("/") or "/") != path:
                self.send_response(404)
                self.end_headers()
                return
            status_, page = callback_page(parse_qs(url.query))
            body = page.encode("utf-8")
            self.send_response(status_)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    class Server(HTTPServer):
        allow_reuse_address = False                               # see _port_free

        def server_bind(self):
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            super().server_bind()

    try:
        server = Server(("127.0.0.1" if u.hostname == "localhost" else u.hostname, u.port or 80), Handler)
    except OSError:
        return False
    server.timeout = 0.5
    stop = threading.Event()
    deadline = time.monotonic() + SESSION_TTL

    def run():
        try:
            while not stop.is_set() and time.monotonic() < deadline:
                server.handle_request()
                with _lock:
                    if _pending.get("session") is None:           # finished (here, on the app or by paste)
                        break
        except OSError:
            pass
        finally:
            server.server_close()
            if _listener.get("server") is server:
                _listener.update(server=None, stop=None, thread=None)

    t = threading.Thread(target=run, name="fyers-login-listener", daemon=True)
    _listener.update(server=server, stop=stop, thread=t)
    t.start()
    return True


def use_direct_redirect() -> dict:
    """Set FYERS_REDIRECT_URI in .env to this app's callback, for when the Fyers app's Redirect URL was changed to it
    (Fyers only sends the code to the address registered there). Only that line changes; the value is a constant."""
    path = P.root / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for ln in lines:
        if ln.strip().startswith("FYERS_REDIRECT_URI="):
            if not done:
                out.append(f"FYERS_REDIRECT_URI={APP_CALLBACK}")
                done = True
            continue                                              # a duplicate line would win at the next start
        out.append(ln)
    if not done:
        out.append(f"FYERS_REDIRECT_URI={APP_CALLBACK}")
    tmp = path.with_name(f".env.{os.getpid()}.tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    from scanner.store import _replace
    _replace(tmp, path)
    os.environ["FYERS_REDIRECT_URI"] = APP_CALLBACK               # .env is read once at start: this process too
    return status()


def extract_code(text: str) -> tuple[str | None, str | None]:
    """(auth_code, state) from a pasted redirect address, or (text, None) for a bare code."""
    from urllib.parse import parse_qs, urlparse
    text = (text or "").strip()
    if "auth_code=" in text:
        q = parse_qs(urlparse(text).query)
        return (q.get("auth_code") or [None])[0], (q.get("state") or [None])[0]
    return (text or None), None


def complete(redirect_url: str) -> dict:
    """The paste flow: the address bar after logging in (or a bare auth code)."""
    code, state = extract_code(redirect_url)
    if not code:
        raise ApiException("VALIDATION", "No auth_code found in the pasted address.",
                           "Paste the full address from the browser bar after logging in.")
    return _finish(code, state, need_state=False)


def _finish(code: str, state: str | None, *, need_state: bool) -> dict:
    """Exchange the auth code of the login started here for today's token and save it. A redirect (callback or
    listener) must carry the login's `state`; a pasted bare code has none (the user copied it from Fyers)."""
    with _lock:
        session, expected = _pending.get("session"), _pending.get("state")
        if session is None or time.monotonic() > _pending.get("expires", 0):
            raise ApiException("VALIDATION", "The login link has expired or was not started here.",
                               "Click 'Log in' again to get a new link.")
        if (need_state or state is not None) and state != expected:
            raise ApiException("FYERS_AUTH", "Security check failed (state mismatch).", "Start the login again.")
        _pending.update(session=None, state=None, expires=0.0)
    cid, _, _ = _credentials()
    try:
        resp = _exchange_code(session, code)
    except requests.Timeout:
        raise ApiException("FYERS_AUTH", "Fyers did not answer in time.",
                           "Check your internet connection and log in again.")
    except Exception as e:
        raise ApiException("FYERS_AUTH", f"Fyers did not accept the code ({type(e).__name__}).", "Log in again.")
    if not isinstance(resp, dict) or "access_token" not in resp:
        msg = resp.get("message") if isinstance(resp, dict) else None
        raise ApiException("FYERS_AUTH", f"Fyers did not return a token{': ' + str(msg) if msg else ''}.",
                           "Check that the App ID, Secret and Redirect URL in .env match your Fyers app exactly.")
    body = json.dumps({"client_id": cid, "access_token": resp["access_token"],
                       "created": now_ist().isoformat(timespec="seconds")})
    tmp = P.token.with_name(P.token.name + f".{os.getpid()}.tmp")
    tmp.write_text(body, encoding="utf-8")
    from scanner.store import _replace
    _replace(tmp, P.token)
    providers._fyers_cache.clear()
    plan = "prime" if str(data.config().get("fyers_plan", "standard")).lower() == "prime" else "standard"
    try:
        ok, name = _profile(providers.FyersProvider(cid, resp["access_token"], plan=plan))
    except Exception:
        ok, name = None, None
    with _lock:
        _verify.update(key=resp["access_token"][-12:], at=time.monotonic(), ok=ok, name=name if ok else None,
                       when=now_ist().isoformat(timespec="seconds"))
    # The token is saved and came from Fyers seconds ago: only an explicit rejection makes the login fail
    # (rate-limit protection or a network blip during the profile check does not).
    return {"ok": ok is not False, "user_name": name if ok else None, "status": status()}


def _exchange_code(session, code: str) -> dict:
    """The auth code -> access token exchange of SessionModel.generate_token() (same URL and payload) with a
    timeout: the SDK posts without one, so a stalled connection would hang this request forever."""
    from fyers_apiv3 import fyersModel
    payload = {"grant_type": getattr(session, "grant_type", None) or "authorization_code",
               "appIdHash": session.get_hash().hexdigest(), "code": code}
    r = requests.post(fyersModel.Config.API + fyersModel.Config.generate_access_token, json=payload, timeout=(5, 20))
    return r.json()


def get_client():
    """A logged-in Fyers client for a POST action (holdings import), or a contract error."""
    cfg = data.config()
    cid, secret = env("FYERS_CLIENT_ID"), env("FYERS_SECRET_KEY")
    if not cid or not secret:
        raise ApiException("FYERS_NOT_CONFIGURED", "FYERS_CLIENT_ID / FYERS_SECRET_KEY are missing in .env.")
    tok = token()
    if not tok or not tok.get("created") or providers.token_expired(tok):
        raise ApiException("FYERS_LOGIN_REQUIRED", "Log in to Fyers first (tokens expire every morning).",
                           "Settings > Fyers > Log in.")
    if running_scan():
        raise ApiException("FYERS_RATE_LIMIT", "A scan is using the Fyers data budget right now.",
                           "Try again when the scan has finished.")
    plan = "prime" if str(cfg.get("fyers_plan", "standard")).lower() == "prime" else "standard"
    return providers.FyersProvider(tok["client_id"], tok["access_token"], plan=plan)
