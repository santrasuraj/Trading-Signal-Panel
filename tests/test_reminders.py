"""The 08:45 FYERS login reminder (scanner/reminders.py): only on trading days, only when today's login is missing."""
from datetime import datetime

from scanner import reminders
from scanner.intraday import fyers_sync
from scanner.settings import IST


def test_reminds_only_on_a_trading_day_without_todays_login(monkeypatch):
    sent = []
    send = lambda text: (sent.append(text) or True, "sent")                      # noqa: E731
    morning = datetime(2026, 11, 12, 8, 45, tzinfo=IST)
    monkeypatch.setattr(fyers_sync, "is_trading_day", lambda d: d.weekday() < 5)
    monkeypatch.setattr(reminders, "logged_in_today", lambda now=None: False)
    r = reminders.check(morning, send)
    assert r["trading_day"] and r["sent"] and "1_login.bat" in sent[0]
    monkeypatch.setattr(reminders, "logged_in_today", lambda now=None: True)
    assert not reminders.check(morning, send)["sent"]
    saturday = datetime(2026, 11, 14, 8, 45, tzinfo=IST)
    r = reminders.check(saturday, send)
    assert not r["trading_day"] and not r["sent"] and len(sent) == 1
