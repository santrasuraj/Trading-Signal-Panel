"""Log in to Fyers (needed once per day - Fyers tokens expire every morning).

Run:  python login.py      (or double-click 1_login.bat)
A browser opens -> log in to Fyers yourself -> the token is saved to data/fyers_token.json.
"""
from __future__ import annotations

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from fyers_apiv3 import fyersModel

from scanner.providers import FyersProvider
from scanner.settings import TOKEN_FILE, env, ist_now

DEFAULT_REDIRECT = "http://127.0.0.1:8765/fyers/callback"


def _extract_code(text: str) -> str | None:
    text = text.strip()
    if "auth_code=" in text:
        return (parse_qs(urlparse(text).query).get("auth_code") or [None])[0]
    return text or None


def _wait_for_redirect(redirect: str, login_url: str) -> str | None:
    """Catch Fyers' redirect on a tiny local web server, so nothing needs to be copy-pasted."""
    parsed = urlparse(redirect)
    captured: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            captured["code"] = (q.get("auth_code") or [None])[0]
            ok = bool(captured["code"])
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = ("✅ Fyers login received. You can close this tab and go back to the scanner."
                   if ok else "❌ No auth code in the redirect. Please try again.")
            self.wfile.write(f"<html><body style='font-family:sans-serif;padding:40px'><h2>{msg}</h2></body></html>".encode())

        def log_message(self, *args):
            pass

    try:
        server = HTTPServer((parsed.hostname, parsed.port or 80), Handler)
    except OSError as e:
        print(f"Could not start local listener on {parsed.hostname}:{parsed.port} ({e}).")
        return None
    server.timeout = 300
    print("Opening the Fyers login page in your browser...")
    print("If it doesn't open, copy this link into your browser:\n", login_url, "\n")
    webbrowser.open(login_url)
    print("Waiting for you to log in (5 minutes max)...")
    server.handle_request()
    server.server_close()
    return captured.get("code")


def main() -> int:
    client_id = env("FYERS_CLIENT_ID")
    secret = env("FYERS_SECRET_KEY")
    redirect = env("FYERS_REDIRECT_URI", DEFAULT_REDIRECT)
    if not client_id or not secret:
        print("FYERS_CLIENT_ID / FYERS_SECRET_KEY are missing.\n"
              "Copy .env.example to .env and fill them in (see README.md, step 2).")
        return 1

    session = fyersModel.SessionModel(client_id=client_id, secret_key=secret, redirect_uri=redirect,
                                      response_type="code", grant_type="authorization_code", state="scanner")
    login_url = session.generate_authcode()

    code = None
    if urlparse(redirect).hostname in ("127.0.0.1", "localhost"):
        code = _wait_for_redirect(redirect, login_url)
    if not code:
        print("\nOpen this link, log in, then copy the FULL address from the browser bar after login:\n")
        print(login_url, "\n")
        webbrowser.open(login_url)
        code = _extract_code(input("Paste the address (or just the auth_code) here: "))
    if not code:
        print("No auth code received. Login cancelled.")
        return 1

    session.set_token(code)
    resp = session.generate_token()
    if not isinstance(resp, dict) or "access_token" not in resp:
        print("Fyers did not return a token:", resp)
        print("Check that the App ID, Secret and Redirect URL in .env match your Fyers app exactly.")
        return 1

    TOKEN_FILE.write_text(json.dumps({
        "client_id": client_id, "access_token": resp["access_token"],
        "created": ist_now().isoformat(timespec="seconds"),
    }), encoding="utf-8")

    ok, name = FyersProvider(client_id, resp["access_token"]).check_login()
    if ok:
        print(f"\n✅ Logged in to Fyers{' as ' + name if name else ''}. Token saved - valid until tomorrow morning.")
        return 0
    print("\n⚠️ Token saved but the profile check failed:", name)
    return 1


if __name__ == "__main__":
    sys.exit(main())
