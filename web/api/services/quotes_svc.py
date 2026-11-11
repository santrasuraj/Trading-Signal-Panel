"""Live prices for the screen, between scans (GET /api/quotes and the /api/stream/quotes event stream).

Sources, best first, per symbol:
  live   the FYERS WebSocket via the live service's quotes.json (scanner/intraday/quote_hub.py): about a second
         old, no REST call at all. Covers the ~100 symbols the live service streams, which follow the screen.
  fyers  FYERS REST quotes when logged in today, through the shared rate limiter (one call per 50 symbols),
         cached 30 s per symbol. The screen never spends the FYERS budget the scans and the 15:45 archive need:
         below FYERS_RESERVE calls left today it uses Yahoo.
  yahoo  ~15 minutes delayed, cached 60 s.
  close  the last stored daily close.

While the market is open every source is tried in that order. From 15:30 to 18:00 (post_close) a symbol shows
its last trade of the day (live feed, else one REST fetch cached 5 minutes) instead of jumping back to the
last scan's price. Outside those hours: the last stored close, with no network call. Prices only: signals
still come from the scans.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from scanner.intraday import quote_hub
from scanner.providers import FyersAuthError, YahooProvider, get_fyers
from scanner.fyers_limits import FyersRateLimited

from . import clock, data
from ..caches import FileCache, register
from ..errors import ApiException, log
from ..paths import P
from ..util import now_ist, num

MAX_SYMBOLS = 100
TTL = {"fyers": 30.0, "yahoo": 60.0}
POST_CLOSE_TTL = 300.0       # after 15:30 the last trade no longer changes: one REST fetch per 5 minutes is plenty
FYERS_RESERVE = 600          # FYERS data calls left today below which the screen switches to Yahoo
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9&_.-]{0,24}$")
_cache: dict[str, tuple[float, str, dict | None]] = {}     # symbol -> (monotonic time, source, quote)
_lock = threading.Lock()
_RANK = {"live": 0, "fyers": 1, "yahoo": 2, "close": 3}
NOTES = {"live": "Real-time FYERS live feed.", "fyers": "Real-time FYERS prices (refreshed every 30 s).",
         "yahoo": "Yahoo prices, ~15 min delayed: log in to FYERS for real time.",
         "close": "Market closed: last closing prices."}


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
                          "time": col.index[-1].date().isoformat(), "source": "close", "delayed": False}
    return out


def _load_hub(path: Path) -> dict:
    info = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(info.get("quotes"), dict):
        raise ValueError("quotes.json without quotes")
    return info


_hub = register(FileCache(_load_hub))


def hub_info() -> dict | None:
    """Today's quotes.json from the live service (None when it hasn't run today). Parsed again only when the
    file changes, so many open streams share one read."""
    info = _hub.get(P.intraday_live / quote_hub.QUOTES_FILE_NAME)
    if not info:
        return None
    try:
        if datetime.fromisoformat(info["updated"]).date() != now_ist().date():
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return info


def cached(syms: list[str]) -> dict[str, dict]:
    """The last REST / Yahoo quote of each symbol from today, however old (no network): what the event stream
    shows for a symbol between its REST refreshes."""
    today = now_ist().date().isoformat()
    with _lock:
        return {s: _cache[s][2] for s in syms
                if s in _cache and _cache[s][2] and str(_cache[s][2].get("time", "")).startswith(today)}


def _from_hub(syms: list[str], info: dict | None) -> dict[str, dict]:
    if not info:
        return {}
    qs = info.get("quotes") or {}
    out = {}
    for s in syms:
        q = qs.get(s)
        if q and q.get("price"):
            out[s] = {k: q.get(k) for k in ("symbol", "price", "prev_close", "change_pct", "time", "open", "high",
                                             "low", "volume", "bid", "ask")}
            out[s].update(source="live", delayed=False)
    return out


def _from_fyers(fy, syms: list[str]) -> dict[str, dict]:
    today = now_ist().date()
    out = {}
    for s, (qdate, row) in fy.live_rows(syms).items():
        lp, prev = num(row.get("close")), num(row.get("prev_close"))
        if not lp or (qdate is not None and qdate != today):
            continue
        out[s] = {"symbol": s, "price": round(lp, 2), "prev_close": prev,
                  "change_pct": round((lp / prev - 1) * 100, 2) if prev else None,
                  "time": now_ist().isoformat(timespec="seconds"), "source": "fyers", "delayed": False,
                  "open": num(row.get("open")), "high": num(row.get("high")), "low": num(row.get("low")),
                  "volume": num(row.get("volume"))}
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
                  "change_pct": round((last / prev - 1) * 100, 2) if prev else None, "time": today.isoformat(),
                  "source": "yahoo", "delayed": True}
    return out


def _tag(quotes: dict[str, dict], source: str) -> dict[str, dict]:
    """Each quote says where it came from (and Yahoo's are delayed)."""
    for v in quotes.values():
        if v:
            v.setdefault("source", source)
            v.setdefault("delayed", source == "yahoo")
    return quotes


def _safe_yahoo(syms: list[str]) -> dict[str, dict]:
    try:
        return _tag(_from_yahoo(syms), "yahoo") if syms else {}
    except Exception:
        log.exception("Yahoo live quotes failed")
        return {}


def _rest(syms: list[str], ttl_override: float | None = None) -> dict[str, dict]:
    """FYERS REST (logged in, budget left) else Yahoo, through the per-symbol cache."""
    if not syms:
        return {}
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
        ttl = ttl_override if ttl_override is not None else TTL[source]
        fresh = {sym: q for sym, (t, src, q) in _cache.items()
                 if sym in syms and src == source and now - t < ttl}
        need = [x for x in syms if x not in fresh]
        got: dict[str, dict] = {}
        if need:
            try:
                got = _tag(_from_fyers(fy, need), "fyers") if fy is not None else _safe_yahoo(need)
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
        return {k: v for k, v in {**fresh, **got}.items() if v}


def quotes(syms: list[str], allow_network: bool = True) -> dict:
    """The best quote for each symbol (see the module docstring). `allow_network=False` (the event stream's
    fast path) uses only the live feed and the cache, never a REST call."""
    clk = clock.market_clock()
    session = clk["session"]
    out: dict[str, dict] = {}
    if session in ("open", "post_close"):
        info = hub_info()
        if session == "post_close" or quote_hub.feed_live(info):
            out.update(_from_hub(syms, info))            # after 15:30 the feed's last trades are the day's last prices
        rest = [x for x in syms if x not in out]
        if rest and allow_network:
            out.update(_rest(rest, ttl_override=POST_CLOSE_TTL if session == "post_close" else None))
        elif rest:
            out.update(cached(rest))
    missing = [x for x in syms if x not in out]
    out.update(_tag(_from_store(missing), "close"))
    got = [q for x in syms for q in [out.get(x)] if q]
    best = min((q["source"] for q in got), key=_RANK.__getitem__, default="close")
    if session not in ("open", "post_close"):
        best = "close"
    delayed = any(q.get("delayed") for q in got)
    note = NOTES[best]
    if session == "post_close" and best != "close":
        note = "Market closed at 15:30: last trades of the day (official close after ~18:00)."
    elif best == "live" and delayed:
        note = "Real-time FYERS live feed; some symbols from Yahoo (~15 min delayed)."
    return {"as_of": now_ist().isoformat(timespec="seconds"), "session": session, "source": best,
            "delayed": delayed, "note": note, "quotes": got}
