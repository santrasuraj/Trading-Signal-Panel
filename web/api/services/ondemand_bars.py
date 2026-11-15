"""Bars on demand for the Chart page: any NSE stock or index, at any timeframe, when the local stores don't have it.

The stores cover what the jobs collect: daily candles of the scan universe (data/store) and 5-minute candles of the
~150 most liquid F&O stocks (data/intraday/bars); 1-minute candles exist only for what the live FYERS feed streamed.
Everything else - another stock, an index such as BANKNIFTY, 1-minute candles - is fetched here when a chart asks:
  * FYERS history (real time) when today's FYERS login is valid - through the shared rate limiter;
  * else Yahoo (about 15 minutes late while the market is open; complete for past sessions).
Each answer is cached for CACHE_OPEN_S while the market is open (an open chart refreshes once a minute) and
CACHE_CLOSED_S otherwise. Nothing is written to the stores: the jobs stay their only writers.
"""
from __future__ import annotations

import threading
import time
from datetime import timedelta

import pandas as pd

from scanner.intraday import data as idata

from . import clock, data
from ..util import now_ist, today_ist

CACHE_OPEN_S = 60
CACHE_CLOSED_S = 1800
CACHE_DAILY_S = 6 * 3600
# the app's index names -> Yahoo and FYERS tickers (the indices the app charts and trades options on)
YAHOO_INDEX = {"NIFTY50": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
               "MIDCPNIFTY": "NIFTY_MID_SELECT.NS", "NIFTYNXT50": "^NSMIDCP", "INDIAVIX": "^INDIAVIX",
               "NIFTY500": "^CRSLDX", "NIFTYIT": "^CNXIT"}
FYERS_INDEX = {"NIFTY50": "NSE:NIFTY50-INDEX", "BANKNIFTY": "NSE:NIFTYBANK-INDEX", "FINNIFTY": "NSE:FINNIFTY-INDEX",
               "MIDCPNIFTY": "NSE:MIDCPNIFTY-INDEX", "NIFTYNXT50": "NSE:NIFTYNXT50-INDEX",
               "INDIAVIX": "NSE:INDIAVIX-INDEX", "NIFTY500": "NSE:NIFTY500-INDEX", "NIFTYIT": "NSE:NIFTYIT-INDEX"}
SOURCE_NOTE = {"fyers": "FYERS history (real time)", "yahoo": "Yahoo (about 15 minutes late while the market is open)"}
_cache: dict = {}
_lock = threading.Lock()


def is_index(symbol: str) -> bool:
    return symbol.upper() in YAHOO_INDEX


def _ttl() -> float:
    try:
        return CACHE_OPEN_S if clock.market_clock()["session"] == "open" else CACHE_CLOSED_S
    except Exception:
        return CACHE_OPEN_S


def _cached(key, ttl: float, fetch):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    val = fetch()
    with _lock:
        _cache[key] = (time.time(), val)
        if len(_cache) > 300:                       # a long day of browsing: drop the oldest
            for k in sorted(_cache, key=lambda k: _cache[k][0])[:100]:
                _cache.pop(k, None)
    return val


def _fyers():
    """Today's FYERS client, or None (not logged in, budget used up) - no network call when there is no login."""
    try:
        from scanner.providers import get_fyers
        fy, _ = get_fyers(data.config())
        return fy
    except Exception:
        return None


def _yahoo(ticker: str, interval: str, period: str) -> pd.DataFrame:
    return idata._yahoo_long(idata._yf_download([ticker], period=period, interval=interval), [ticker])


def intraday(symbol: str, interval: str, days: int) -> tuple[pd.DataFrame, str | None]:
    """The last `days` sessions of 1- or 5-minute candles (cleaned; the forming one flagged) and their source."""
    sym = symbol.upper()

    def fetch():
        now = now_ist().replace(tzinfo=None)
        fy = _fyers()
        if fy is not None:
            try:
                raw = idata.fetch_fyers_intraday(fy, [FYERS_INDEX.get(sym, f"NSE:{sym}-EQ")],
                                                 today_ist() - timedelta(days=days * 2 + 7), today_ist(),
                                                 resolution=interval)
                if len(raw):
                    return idata.clean_bars(raw.assign(symbol=sym), interval, now=now), "fyers"
            except Exception:
                pass                                 # login expired, budget, network: Yahoo below
        maxd = 8 if interval == "1m" else 60
        raw = _yahoo(YAHOO_INDEX.get(sym, f"{sym}.NS"), interval, f"{min(days * 2 + 5, maxd)}d")
        if raw.empty:
            return idata.empty_bars(), None
        clean = idata.clean_bars(raw.assign(symbol=sym, source="yahoo"), interval, drop_synthetic_close=True, now=now)
        return clean, "yahoo"

    df, src = _cached(("i", sym, interval, days), _ttl(), fetch)
    if df.empty:
        return df, src
    sessions = sorted(df["ts"].dt.normalize().unique())[-days:]
    return df[df["ts"].dt.normalize().isin(sessions)].reset_index(drop=True), src


def daily(symbol: str) -> tuple[pd.DataFrame, str | None]:
    """Daily candles (date index; open, high, low, close, volume) for a symbol the daily store doesn't have."""
    sym = symbol.upper()

    def fetch():
        raw = _yahoo(YAHOO_INDEX.get(sym, f"{sym}.NS"), "1d", "max")
        if raw.empty:
            return pd.DataFrame(), None
        df = raw.set_index(pd.to_datetime(raw["ts"]).dt.normalize())[["open", "high", "low", "close", "volume"]]
        df = df[~df.index.duplicated(keep="last")].dropna(subset=["close"]).sort_index()
        df["volume"] = df["volume"].fillna(0.0)
        for f in ("open", "high", "low"):
            df[f] = df[f].fillna(df["close"])
        return df, "yahoo"

    return _cached(("d", sym), CACHE_DAILY_S, fetch)
