"""Log in to Fyers (needed once per day - Fyers tokens expire every morning).

Run:  python login.py      (or double-click 1_login.bat)
A browser opens -> log in to Fyers yourself -> the token is saved to data/fyers_token.json.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from fyers_apiv3 import fyersModel

from scanner.providers import FyersProvider
from scanner.settings import TOKEN_FILE, env, ist_now

DEFAULT_REDIRECT = "http://127.0.0.1:8000/api/v1/auth/callback"


def _replace(src, dst, tries: int = 10) -> None:
    """os.replace with retries: on Windows it fails while another process has the target open."""
    for i in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.2 * (i + 1))


def _extract_code(text: str) -> str | None:
    text = text.strip()
    if "auth_code=" in text:
        return (parse_qs(urlparse(text).query).get("auth_code") or [None])[0]
    return text or None


def _wait_for_redirect(redirect: str, login_url: str, state: str) -> str | None:
    """Catch Fyers' redirect on a tiny local web server, so nothing needs to be copy-pasted.
    Only a request to the exact callback path carrying our random `state` is accepted."""
    parsed = urlparse(redirect)
    callback_path = parsed.path or "/"
    captured: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            if url.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return
            q = parse_qs(url.query)
            code = (q.get("auth_code") or [None])[0]
            ok = bool(code) and (q.get("state") or [None])[0] == state
            if ok:
                captured["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = ("✅ Fyers login received. You can close this tab and go back to the scanner."
                   if ok else "❌ Login was not completed (missing code or security check failed). Please try again.")
            self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'><h2>{msg}</h2></body></html>".encode())

        def log_message(self, *args):
            pass

    try:
        server = HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    except OSError as e:
        print(f"Could not start local listener on {parsed.hostname}:{parsed.port} ({e}).\n"
              "Is another program using that port? Close it, or use the copy-paste method below.")
        return None
    server.timeout = 5
    print("Opening the Fyers login page in your browser...")
    print("If it doesn't open, copy this link into your browser:\n", login_url, "\n")
    webbrowser.open(login_url)
    print("Waiting for you to log in (5 minutes max)...")
    deadline = time.monotonic() + 300
    while "code" not in captured and time.monotonic() < deadline:
        server.handle_request()
    server.server_close()
    return captured.get("code")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):   # the ✅ / ⚠️ messages must not crash a redirected (cp1252) stdout
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    client_id = env("FYERS_CLIENT_ID")
    secret = env("FYERS_SECRET_KEY")
    redirect = env("FYERS_REDIRECT_URI", DEFAULT_REDIRECT)
    if not client_id or not secret:
        print("FYERS_CLIENT_ID / FYERS_SECRET_KEY are missing.\n"
              "Copy .env.example to .env and fill them in (see README.md, step 2).")
        return 1

    state = secrets.token_urlsafe(16)
    session = fyersModel.SessionModel(client_id=client_id, secret_key=secret, redirect_uri=redirect,
                                      response_type="code", grant_type="authorization_code", state=state)
    login_url = session.generate_authcode()

    code = None
    if urlparse(redirect).hostname in ("127.0.0.1", "localhost"):
        code = _wait_for_redirect(redirect, login_url, state)
    if not code:
        print("\n1. A Fyers login page is opening in your browser (link below if it doesn't).")
        print("2. Log in. Afterwards the browser may show an error or another app's page - that is fine.")
        print("3. Copy the FULL address from the browser's address bar (it contains 'auth_code=') and paste it here.\n")
        print(login_url, "\n")
        webbrowser.open(login_url)
        code = _extract_code(input("Paste the address here and press Enter: "))
    if not code:
        print("No auth code received. Login cancelled.")
        return 1

    session.set_token(code)
    try:
        resp = session.generate_token()      # requests.post + .json(): network errors / non-JSON replies raise
    except Exception as e:
        print(f"Could not reach Fyers to exchange the login code ({type(e).__name__}). "
              "Check your internet connection and run the login again.")
        return 1
    if not isinstance(resp, dict) or "access_token" not in resp:
        print("Fyers did not return a token:", resp)
        print("Check that the App ID, Secret and Redirect URL in .env match your Fyers app exactly.")
        return 1

    # Atomic write: the scanner / web API may read the token file at this very moment.
    tmp = TOKEN_FILE.with_name(f"{TOKEN_FILE.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps({
            "client_id": client_id, "access_token": resp["access_token"],
            "created": ist_now().isoformat(timespec="seconds"),
        }), encoding="utf-8")
        _replace(tmp, TOKEN_FILE)
    except OSError as e:
        print(f"Could not save the Fyers token to {TOKEN_FILE} ({type(e).__name__}). "
              "Close any program using that file and run the login again.")
        return 1

    try:
        ok, name = FyersProvider(client_id, resp["access_token"]).check_login()
    except Exception as e:
        ok, name = False, type(e).__name__
    if ok:
        print(f"\n✅ Logged in to Fyers{' as ' + name if name else ''}. Token saved - valid until tomorrow morning.")
        return 0
    print("\n⚠️ Token saved but the profile check failed:", name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
