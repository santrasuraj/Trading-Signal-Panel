"""IST market clock from cached files only (data/nse/holidays_<year>.json + the store's holiday list).

Sessions: weekend / holiday; 09:00-09:15 pre_open; 09:15-15:30 open; 15:30-18:00 post_close; else closed.
last_completed_day = today if it is a trading day and now >= 18:00 (NSE publishes its official file
around then), else the previous trading day. AsOf.stale = data_date < last_completed_day.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from scanner.settings import IST

from . import data
from ..util import now_ist

EOD_HOUR = 18


def _holiday_map(year: int) -> tuple[dict[str, str], bool]:
    out: dict[str, str] = {}
    for y in (year - 1, year, year + 1):
        out.update(data.holidays(y) or {})
    for d in data.store_meta().get("holidays") or []:     # remembered by the store (as store.trading_today uses)
        out.setdefault(str(d)[:10], "Holiday")
    return out, data.holidays(year) is not None


def is_trading_day(d: date, hol: dict[str, str]) -> bool:
    return d.weekday() < 5 and d.isoformat() not in hol


def previous_trading_day(d: date, hol: dict[str, str]) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d, hol):
        d -= timedelta(days=1)
    return d


def market_clock(now: datetime | None = None) -> dict:
    now = now or now_ist()
    today = now.date()
    hol, known = _holiday_map(today.year)
    trading = is_trading_day(today, hol)
    t = now.time()
    if today.weekday() >= 5:
        session = "weekend"
    elif not trading:
        session = "holiday"
    elif time(9, 0) <= t < time(9, 15):
        session = "pre_open"
    elif time(9, 15) <= t < time(15, 30):
        session = "open"
    elif time(15, 30) <= t < time(EOD_HOUR, 0):
        session = "post_close"
    else:
        session = "closed"
    nxt = today if trading and t < time(9, 15) else today + timedelta(days=1)
    for _ in range(15):
        if is_trading_day(nxt, hol):
            break
        nxt += timedelta(days=1)
    next_open = datetime.combine(nxt, time(9, 15), IST).isoformat(timespec="seconds")
    last_done = today if trading and t >= time(EOD_HOUR, 0) else previous_trading_day(today, hol)
    return {"now": now.isoformat(timespec="seconds"), "session": session, "is_trading_day": trading,
            "holiday_name": hol.get(today.isoformat()) if not trading and today.weekday() < 5 else None,
            "next_open": next_open, "last_completed_day": last_done.isoformat(), "holidays_known": known}
