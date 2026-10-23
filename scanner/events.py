"""NSE event calendar (upcoming financial results) and the official trading-holiday list.

  https://www.nseindia.com/api/event-calendar          results / board meetings, ~3 weeks ahead
  https://www.nseindia.com/api/holiday-master?type=trading

NSE's API needs a browser User-Agent (other clients are silently stalled until timeout), so every
call has a timeout. Results are cached for the day; failures return empty data, never crash a scan.
"""
from __future__ import annotations

import json
import time
from datetime import date, timedelta

import pandas as pd
import requests

from .nse import NSE_DIR

API = "https://www.nseindia.com/api/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
_session: requests.Session | None = None


def _get_json(path: str, params: dict | None = None):
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update(HEADERS)
        try:
            _session.get("https://www.nseindia.com/", timeout=15)  # picks up NSE's cookies
        except requests.RequestException:
            pass
    for attempt in range(3):
        try:
            r = _session.get(API + path, params=params, timeout=20)
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code in (401, 403) and attempt == 0:
            _session.cookies.clear()
            try:
                _session.get("https://www.nseindia.com/", timeout=15)
            except requests.RequestException:
                pass
            continue
        if r.status_code == 200:
            return r.json()
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"NSE API {path} unavailable")


def _cached(name: str, max_age_s: float, fetch):
    path = NSE_DIR / name
    if path.exists() and time.time() - path.stat().st_mtime < max_age_s:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    data = fetch()
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def upcoming_results(symbols, today: date, days: int = 14) -> tuple[dict[str, str], str]:
    """{symbol: 'YYYY-MM-DD'} of the next results board meeting within `days`, and a status note."""
    def fetch():
        params = {"index": "equities", "from_date": today.strftime("%d-%m-%Y"),
                  "to_date": (today + timedelta(days=days)).strftime("%d-%m-%Y")}
        return _get_json("event-calendar", params)
    try:
        rows = _cached(f"events_{today:%Y%m%d}.json", 6 * 3600, fetch)
    except Exception:
        return {}, "Results calendar unavailable (NSE did not respond)"
    wanted = set(symbols)
    out: dict[str, str] = {}
    for r in rows:
        sym = str(r.get("symbol", "")).strip()
        if sym not in wanted or "result" not in str(r.get("purpose", "")).lower():
            continue
        try:
            d = pd.to_datetime(str(r.get("date", "")).strip().title(), format="%d-%b-%Y").date()
        except (ValueError, TypeError):
            continue
        if today <= d <= today + timedelta(days=days) and (sym not in out or d.isoformat() < out[sym]):
            out[sym] = d.isoformat()
    return out, f"Results calendar: {len(out)} of your stocks report in the next {days} days"


def trading_holidays(year: int) -> set[str]:
    """Official NSE equity trading holidays for `year` as ISO dates (empty set if unavailable)."""
    try:
        raw = _cached(f"holidays_{year}.json", 7 * 86400, lambda: _get_json("holiday-master", {"type": "trading"}))
    except Exception:
        return set()
    out = set()
    for r in raw.get("CM", []):
        try:
            d = pd.to_datetime(str(r.get("tradingDate", "")).strip().title(), format="%d-%b-%Y").date()
        except (ValueError, TypeError):
            continue
        if d.year == year:
            out.add(d.isoformat())
    return out
