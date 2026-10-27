"""GET /api/quotes: live prices for the screen, between scans.

While the market is open: FYERS quotes (real time) when logged in today, through the shared rate limiter (one
call per 50 symbols); otherwise Yahoo (~15 min delayed). Each symbol's quote is cached (FYERS 30 s, Yahoo 60 s)
and only stale symbols are fetched, so the top bar and the Signals page share calls. The screen never spends the
FYERS budget the scans and the 15:45 archive need: below FYERS_RESERVE calls left today it uses Yahoo. Outside
market hours: the last stored close, with no network call at all. Prices only: signals still come from the scans.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import timedelta

from scanner.providers import FyersAuthError, YahooProvider, get_fyers
from scanner.fyers_limits import FyersRateLimited

from . import clock, data
from ..errors import ApiException, log
from ..util import now_ist, num

MAX_SYMBOLS = 100
TTL = {"fyers": 30.0, "yahoo": 60.0}
FYERS_RESERVE = 600          # FYERS data calls left today below which the screen switches to Yahoo
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9&_.-]{0,24}$")
_cache: dict[str, tuple[float, str, dict]] = {}     # symbol -> (monotonic time, source, quote)
_lock = threading.Lock()


def parse(symbols: str) -> list[str]:
    syms = list(dict.fromkeys(s.strip().upper() for s in symbols.split(",") if s.strip()))
    bad = [s for s in syms if not SYMBOL.match(s)]
    if bad or not syms or len(syms) > MAX_SYMBOLS:
        raise ApiException("VALIDATION", f"Give 1-{MAX_SYMBOLS} NSE symbols, comma separated"
                           + (f" (not a symbol: {bad[0]})" if bad else "") + ".")
    return syms


def _from_store(syms: list[str]) -> dict[str, dict]:
    try:
        c = data.store_close()
    except Exception:
        return {}
    out = {}
    for s in syms:
        if s in c.columns:
            col = c[s].dropna()
            if len(col):
                last = float(col.iloc[-1])
                prev = float(col.iloc[-2]) if len(col) > 1 else None
                out[s] = {"symbol": s, "price": round(last, 2), "prev_close": round(prev, 2) if prev else None,
                          "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
                          "time": col.index[-1].date().isoformat()}
    return out


def _from_fyers(fy, syms: list[str]) -> dict[str, dict]:
    today = now_ist().date()
    out = {}
    for s, (qdate, row) in fy.live_rows(syms).items():
        lp, prev = num(row.get("close")), num(row.get("prev_close"))
        if not lp or (qdate is not None and qdate != today):
            continue
        out[s] = {"symbol": s, "price": round(lp, 2), "prev_close": prev,
                  "change_pct": round((lp / prev - 1) * 100, 2) if prev else None, "time": now_ist().isoformat(timespec="seconds")}
    return out


def _from_yahoo(syms: list[str]) -> dict[str, dict]:
    today = now_ist().date()
    out = {}
    for s, df in YahooProvider().history(syms, {s: today - timedelta(days=7) for s in syms}, today).items():
        df = df.dropna(subset=["close"]) if len(df) else df
        if not len(df) or df.index[-1].date() != today:
            continue                                    # no trade yet today: the stored close is shown instead
        last = float(df["close"].iloc[-1])
        prev = float(df["close"].iloc[-2]) if len(df) > 1 else None
        out[s] = {"symbol": s, "price": round(last, 2), "prev_close": round(prev, 2) if prev else None,
                  "change_pct": round((last / prev - 1) * 100, 2) if prev else None, "time": today.isoformat()}
    return out


def quotes(syms: list[str]) -> dict:
    clk = clock.market_clock()
    if clk["session"] != "open":
        return {"as_of": now_ist().isoformat(timespec="seconds"), "session": clk["session"], "source": "close",
                "delayed": False, "note": "Market closed: last closing prices.", "quotes": list(_from_store(syms).values())}
    fy = None
    try:
        fy, _ = get_fyers(data.config())
        if fy is not None and fy.limiter.usage()["data"]["remaining_today"] < FYERS_RESERVE:
            fy = None                                    # keep the rest of today's budget for the scans
    except Exception:           # never let a broken login take down the page: Yahoo instead
        log.exception("Fyers login check for live quotes failed")
    source = "fyers" if fy is not None else "yahoo"
    with _lock:                                          # one fetch at a time: no duplicate calls for a symbol
        now = time.monotonic()
        fresh = {sym: q for sym, (t, src, q) in _cache.items()
                 if sym in syms and src == source and now - t < TTL[source]}
        need = [x for x in syms if x not in fresh]
        got: dict[str, dict] = {}
        if need:
            try:
                got = _from_fyers(fy, need) if fy is not None else _safe_yahoo(need)
            except (FyersAuthError, FyersRateLimited):   # expired login / budget protection: Yahoo instead
                source = "yahoo"
                got = _safe_yahoo(need)
            except Exception:
                log.exception("Live quotes failed")
            if source == "fyers" and len(got) < len(need):   # FYERS answered for part of the list only
                got.update(_safe_yahoo([x for x in need if x not in got]))
            for sym in need:                             # no trade yet today is remembered too (None)
                _cache[sym] = (now, source, got.get(sym))
            if len(_cache) > 2000:
                _cache.clear()
        live = {k: v for k, v in {**fresh, **got}.items() if v}
        rest = _from_store([x for x in syms if x not in live])  # not traded yet today: last close
        return {"as_of": now_ist().isoformat(timespec="seconds"), "session": clk["session"], "source": source,
                "delayed": source != "fyers",
                "note": ("Real-time FYERS prices." if source == "fyers"
                         else "Yahoo prices, ~15 min delayed: log in to FYERS for real time."),
                "quotes": [q for x in syms for q in [live.get(x) or rest.get(x)] if q]}


def _safe_yahoo(syms: list[str]) -> dict[str, dict]:
    try:
        return _from_yahoo(syms) if syms else {}
    except Exception:
        log.exception("Yahoo live quotes failed")
        return {}
