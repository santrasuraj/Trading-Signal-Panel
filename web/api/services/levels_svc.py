"""Price action for one symbol (scanner/levels.py): daily bars from the price store, today's 5-minute bars from the
FYERS live feed (data/intraday/live/) or else the newest stored session (data/intraday/bars/). Files only."""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from scanner import levels, pattern_study
from scanner.intraday import data as idata
from scanner.intraday.live import live_file

from ..caches import FileCache, KeyedCache, file_key, register
from . import chart_data
from ..paths import P
from ..util import today_ist

NOTE = ("Descriptive price action, not a signal. Pivots are for the next session, from the last completed day. "
        "Support and resistance are price zones where the stock turned before (merged within half a day's average "
        "range). Every candle and chart pattern carries its tested record (pattern study, 8 years of the "
        "survivorship-free top 500): none beat the average stock after costs; gap-ups and ascending triangles did "
        "worse than it.")
STORED_DAYS = 10             # look this far back for the newest stored 5-minute session

_cache = register(KeyedCache(32))
_study = register(FileCache(lambda p: json.loads(p.read_text(encoding="utf-8")), missing=None))
STUDY_NOTE = ("Each pattern on 8 years of the survivorship-free top 500: bought at the next open after it appeared "
              "(using only data up to that day), measured against the average top-500 stock over the same days, in "
              "the pattern's direction. t on monthly averages. 'Edge' needs the excess to clear round-trip costs "
              "with t >= 2 on enough events and months.")


def study() -> dict | None:
    return _study.get(P.results / pattern_study.RESULT_FILE.name)


def _evidence(key: str, st: dict | None) -> dict | None:
    p = (st or {}).get("patterns", {}).get(key)
    if not p:
        return None
    return {**p["horizons"][str(p["primary"])], "verdict": p["verdict"], "horizon_days": p["primary"]}


def evidence_table() -> dict:
    st = study() or {}
    rows = [{"key": k, **{f: v[f] for f in ("family", "name", "bias", "verdict", "primary", "horizons")}}
            for k, v in sorted((st.get("patterns") or {}).items(), key=lambda kv: (kv[1]["family"], kv[1]["name"]))]
    return {**{f: st.get(f) for f in ("generated_at", "first_day", "last_day", "events", "cost_pct", "min_events",
                                      "min_months")}, "patterns": rows, "note": STUDY_NOTE}


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
           file_key(live_file(P.data / "intraday")), file_key(P.results / pattern_study.RESULT_FILE.name))

    def compute() -> dict:
        bars, source = _intraday_bars(sym)
        out = levels.analyse(daily, bars)
        st = study()                  # tested on daily bars: never attached to the 5-minute patterns
        d = out["daily"] or {}
        for p in d.get("patterns", []) + d.get("chart_patterns", []):
            p["evidence"] = _evidence(p["key"], st)
        return {"symbol": sym, **out, "intraday_source": source if out["intraday"] else None, "note": NOTE}

    return _cache.get(key, compute)
