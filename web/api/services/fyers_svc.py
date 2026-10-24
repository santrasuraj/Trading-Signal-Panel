"""Fyers status (file reads only unless verify=true), the paste login flow and the legacy login window.

Never returned: .env values, the access token, the secret. The client id is masked (ABCD****-100).
The auth code travels only in a POST body. Token file format = login.py's {client_id, access_token, created}.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import threading
import time
from datetime import timedelta

import requests

from scanner import providers
from scanner.fyers_limits import FyersRateLimited
from scanner.lock import running_scan
from scanner.settings import env

from . import data
from ..errors import ApiException
from ..paths import P
from ..util import now_ist, today_ist

DEFAULT_REDIRECT = "http://127.0.0.1:8000/api/v1/auth/callback"   # login.DEFAULT_REDIRECT
VERIFY_TTL = 300
SESSION_TTL = 600

_lock = threading.Lock()
_verify: dict = {"key": None, "at": 0.0, "ok": None, "name": None, "when": None}
_pending: dict = {"session": None, "state": None, "expires": 0.0}


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
    today_tok = bool(created and str(created)[:10] == today_ist().isoformat())
    plan = "prime" if str(cfg.get("fyers_plan", "standard")).lower() == "prime" else "standard"
    source = "yahoo" if str(cfg.get("data_source", "auto")).lower() == "yahoo" else "auto"
    out = {"configured": bool(cid and secret), "client_id_masked": _mask(cid), "plan": plan, "data_source": source,
           "token_present": tok is not None, "token_created": created, "logged_in_today": today_tok,
           "verified": None, "verified_at": None, "user_name": None,
           "redirect_uri": env("FYERS_REDIRECT_URI", DEFAULT_REDIRECT), "login_modes": ["paste", "window"]}
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
    return {"mode": "paste", "login_url": url, "expires_at": expires,
            "instructions": ["Open the Fyers login page (new tab) and log in.",
                             "Afterwards the browser may show an error or another app's page - that is fine.",
                             "Copy the FULL address from the address bar (it contains 'auth_code=') and paste it here.",
                             "The login link expires in 10 minutes."]}


def extract_code(text: str) -> tuple[str | None, str | None]:
    """(auth_code, state) from a pasted redirect address, or (text, None) for a bare code."""
    from urllib.parse import parse_qs, urlparse
    text = (text or "").strip()
    if "auth_code=" in text:
        q = parse_qs(urlparse(text).query)
        return (q.get("auth_code") or [None])[0], (q.get("state") or [None])[0]
    return (text or None), None


def complete(redirect_url: str) -> dict:
    code, state = extract_code(redirect_url)
    if not code:
        raise ApiException("VALIDATION", "No auth_code found in the pasted address.",
                           "Paste the full address from the browser bar after logging in.")
    with _lock:
        session, expected = _pending.get("session"), _pending.get("state")
        if session is None or time.monotonic() > _pending.get("expires", 0):
            raise ApiException("VALIDATION", "The login link has expired or was not started here.",
                               "Click 'Log in' again to get a new link.")
        if state is not None and state != expected:
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
    if not tok or str(tok.get("created", ""))[:10] != today_ist().isoformat():
        raise ApiException("FYERS_LOGIN_REQUIRED", "Log in to Fyers first (tokens expire every morning).",
                           "Settings > Fyers > Log in.")
    if running_scan():
        raise ApiException("FYERS_RATE_LIMIT", "A scan is using the Fyers data budget right now.",
                           "Try again when the scan has finished.")
    plan = "prime" if str(cfg.get("fyers_plan", "standard")).lower() == "prime" else "standard"
    return providers.FyersProvider(tok["client_id"], tok["access_token"], plan=plan)
