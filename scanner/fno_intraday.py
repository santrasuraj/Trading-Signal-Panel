"""Live F&O positioning during the session, from NSE's OI-spurts feed:

  www.nseindia.com/api/live-analysis-oi-spurts-underlyings    every F&O underlying (~224): today's open interest
                                                              of ALL its futures and options contracts, yesterday's,
                                                              the change, contracts traded, and the spot (in whole
                                                              rupees), stamped with NSE's own time

This is not the end-of-day futures table (fno.py, NSE's F&O bhavcopy after the close): live OI here counts options
too, so it moves far more than futures OI - an expiry week's option writing can add 30% to an index's OI in a day.
A build-up therefore needs a MIN_OI_PCT change. Prices come from the caller (FYERS real time when logged in, else
Yahoo ~15 min delayed); the feed's rounded spot only fills in for indices. Network only in fetch(); positioning,
not a signal.
"""
from __future__ import annotations

import json
from datetime import datetime

from . import fno
from . import smart_money as sm
from .settings import IST

URL = sm.API + "live-analysis-oi-spurts-underlyings"
PAGE = "https://www.nseindia.com/market-data/oi-spurts"
LIVE_NAME = "live_oi.json"
MIN_OI_PCT = 5.0             # live OI includes options (options.py uses 5% too); futures-only EOD uses 2%
MIN_PRICE_PCT = 0.0          # any move counts for the direction (the OI change is the filter)


def _time(s: str | None) -> str | None:
    try:
        return datetime.strptime(str(s).strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return None


def _day(s: str | None) -> str | None:
    try:
        return datetime.strptime(str(s).strip(), "%d-%b-%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def parse(payload: dict) -> dict | None:
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return None
    out = []
    for r in rows:
        sym = str(r.get("symbol") or "").strip().upper()
        oi, prev = _f(r.get("latestOI")), _f(r.get("prevOI"))
        if not sym or oi is None:
            continue
        chg = _f(r.get("changeInOI"))
        out.append({"symbol": sym, "oi": oi, "prev_oi": prev, "oi_chg": chg if chg is not None else (oi - prev if prev else None),
                    "oi_chg_pct": round((oi / prev - 1) * 100, 2) if prev else None,
                    "volume": _f(r.get("volume")), "spot_rounded": _f(r.get("underlyingValue"))})
    return {"nse_time": _time(payload.get("timestamp")), "trade_date": _day(payload.get("currTradingDate")),
            "prev_date": _day(payload.get("prevTradingDate")), "rows": out, "source": PAGE}


def classify(price_chg_pct: float | None, oi_chg_pct: float | None, min_oi_pct: float = MIN_OI_PCT) -> str | None:
    if price_chg_pct is None or oi_chg_pct is None or abs(oi_chg_pct) < min_oi_pct:
        return None
    up = price_chg_pct > MIN_PRICE_PCT
    if oi_chg_pct > 0:
        return "long_buildup" if up else "short_buildup"
    return "short_covering" if up else "long_unwinding"


def fetch() -> tuple[dict | None, str | None]:
    """(parsed feed, error). Never raises."""
    sm._reset_api()
    code, body = sm._fetch(URL, None, api=True, referer=PAGE)
    if code != 200 or not body:
        return None, f"NSE OI-spurts feed: HTTP {code}"
    try:
        d = parse(json.loads(body))
    except ValueError:
        return None, "NSE OI-spurts feed: not JSON (NSE may have changed it)"
    if not d or not d["rows"]:
        return None, "NSE OI-spurts feed: no rows"
    return d, None


def save(view: dict) -> None:
    fno.FNO_DIR.mkdir(parents=True, exist_ok=True)
    sm._save_json(view, fno.FNO_DIR / LIVE_NAME)


def load() -> dict | None:
    try:
        return json.loads((fno.FNO_DIR / LIVE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
