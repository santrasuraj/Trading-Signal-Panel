"""Morning reminder to log in to FYERS: API access needs a fresh login every trading day (SEBI's retail algo
framework), and live prices, the order feed and order placement all wait for it.

Runs at 08:45 on weekdays (setup_schedule.ps1, task "NSE Scanner login reminder"): on an NSE holiday, or when
today's login is already done, it does nothing. Otherwise it sends a Telegram message (when TELEGRAM_BOT_TOKEN and
TELEGRAM_CHAT_ID are set in .env) and always writes a line to data/logs/reminders.log. No FYERS call is made: the
saved token is checked locally.

    python -m scanner.reminders            # what the scheduled task runs
    python -m scanner.reminders --dry-run  # say what it would do, send nothing
"""
from __future__ import annotations

import sys
from datetime import datetime

from .settings import LOG_DIR, ist_now

MESSAGE = ("Good morning. Log in to FYERS for today: double-click 1_login.bat (or Log in on the dashboard). "
           "Live prices, FYERS order updates and order placement need today's login. The market opens at 09:15.")


def logged_in_today(now: datetime | None = None) -> bool:
    """A saved FYERS token from today's session (created after 06:00 IST and not expired), checked locally."""
    from .intraday.live import _token_ok
    from .providers import load_token, token_expired
    tok = load_token()
    return bool(tok) and not token_expired(tok, now) and _token_ok(tok)


def check(now: datetime | None = None, send=None) -> dict:
    """What the reminder does now: {"trading_day", "logged_in", "sent", "detail"}. `send(text) -> (ok, detail)`
    defaults to Telegram."""
    from .intraday.fyers_sync import is_trading_day
    now = now or ist_now()
    out = {"at": now.isoformat(timespec="seconds"), "trading_day": is_trading_day(now.date()), "logged_in": None,
           "sent": False, "detail": ""}
    if not out["trading_day"]:
        out["detail"] = "not a trading day"
        return out
    out["logged_in"] = logged_in_today(now)
    if out["logged_in"]:
        out["detail"] = "already logged in to FYERS today"
        return out
    if send is None:
        from .alerts import send_telegram as send
    ok, detail = send(MESSAGE)
    out["sent"], out["detail"] = bool(ok), str(detail or ("sent" if ok else "not sent"))
    return out


def _log(line: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "reminders.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main(argv: list[str]) -> int:
    if "--dry-run" in argv:
        r = check(send=lambda text: (False, f"dry run, would send: {text}"))
    else:
        r = check()
    line = (f"{r['at']} login reminder: trading day={r['trading_day']} logged in={r['logged_in']} "
            f"sent={r['sent']} ({r['detail']})")
    _log(line)
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
