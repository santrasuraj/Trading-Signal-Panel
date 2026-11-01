"""Price action for one symbol (scanner/levels.py): daily bars from the price store, today's 5-minute bars from the
FYERS live feed (data/intraday/live/) or else the newest stored session (data/intraday/bars/). Files only."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from scanner import levels
from scanner.intraday import data as idata
from scanner.intraday.live import live_file

from ..caches import KeyedCache, file_key, register
from . import chart_data
from ..paths import P
from ..util import today_ist

NOTE = ("Descriptive price action, not a signal. Pivots are for the next session, from the last completed day. "
        "Support and resistance are price zones where the stock turned before (merged within half a day's average "
        "range). Candle patterns are folklore-grade: this app's own test of NR7 breakouts lost money after costs.")
STORED_DAYS = 10             # look this far back for the newest stored 5-minute session

_cache = register(KeyedCache(32))


def _intraday_bars(symbol: str) -> tuple[pd.DataFrame | None, str | None]:
    live = idata.empty_bars()
    p = live_file(P.data / "intraday")
    if p.exists():
        try:
            live = pd.read_parquet(p)
        except Exception:        # mid-write: the stored bars below still answer
            live = idata.empty_bars()
    live = live[live["symbol"].astype(str) == symbol]
    if len(live):
        return live, "live"
    today = today_ist()
    stored = idata.IntradayStore(P.intraday_bars).load("5m", [symbol], start=today - timedelta(days=STORED_DAYS))
    return (stored, "stored") if len(stored) else (None, None)


def levels_for(symbol: str) -> dict:
    sym = symbol.upper()
    daily = chart_data.bars_frame(sym)                    # NOT_FOUND when the store has no such symbol
    month = P.intraday_bars / "5m" / f"{today_ist():%Y-%m}.parquet"
    key = (sym, len(daily), float(daily["close"].iloc[-1]), file_key(month),
           file_key(live_file(P.data / "intraday")))

    def compute() -> dict:
        bars, source = _intraday_bars(sym)
        out = levels.analyse(daily, bars)
        return {"symbol": sym, **out, "intraday_source": source if out["intraday"] else None, "note": NOTE}

    return _cache.get(key, compute)
