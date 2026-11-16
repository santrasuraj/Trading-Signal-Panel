"""Seasonality (GET /api/seasonality/{symbol}) and the market heatmap (GET /api/heatmap).

Seasonality: each calendar month's return of the stock in every year of the price store, the average, the median, how
many years were up, and a t-statistic - next to the Nifty 50 in the same months. Ten or so years per month is a small
sample: a month whose t-statistic is below 2 is shown as noise, not as a pattern.

Heatmap: today's universe (the scan's screener) grouped by industry, each stock sized by its 20-day traded value (NSE
does not publish free-float market caps in the day files; traded value is the closest free proxy) and coloured by its
move over the chosen period. From 09:15 to 18:00 the day's move is the freshest one already at hand - the live feed's
tick, else today's cached FYERS / Yahoo quote (Yahoo ~15 minutes late), else the last scan's - and the page answers at
once: the ~480 quotes (about a minute from Yahoo) are refreshed in the background and show on the next load. Each
stock says where its move came from, and the answer says how old the quotes are.
"""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime

import numpy as np
import pandas as pd

from scanner.providers import INDEX_NIFTY
from scanner.settings import IST

from . import data, quotes_svc
from ..errors import ApiException, log, not_found
from ..util import now_ist

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
PERIODS = {"1d": "change_pct", "1w": "ret_1w", "1m": "ret_1m", "3m": "ret_3m", "12m": "ret_12m"}


def _monthly(close: pd.Series) -> pd.DataFrame:
    """Year x month table of monthly returns (%), from month-end closes (the current month only once it ends)."""
    s = close.dropna()
    if s.empty:
        return pd.DataFrame()
    me = s.groupby(s.index.to_period("M")).last()
    r = (me.pct_change() * 100).dropna()
    last = s.index[-1]
    if r.index[-1] == last.to_period("M") and last.month == (last + pd.offsets.BDay(1)).month:
        r = r.iloc[:-1]                      # the month is not over yet
    t = pd.DataFrame({"year": r.index.year, "month": r.index.month, "ret": r.to_numpy()})
    return t.pivot(index="year", columns="month", values="ret")


def _stats(col: pd.Series) -> dict:
    v = col.dropna().to_numpy(dtype=float)
    n = len(v)
    if n == 0:
        return {"n": 0, "avg": None, "median": None, "up_pct": None, "t": None}
    sd = v.std(ddof=1) if n > 1 else float("nan")
    t = float(v.mean() / (sd / math.sqrt(n))) if n > 2 and sd > 0 else None
    return {"n": n, "avg": round(float(v.mean()), 2), "median": round(float(np.median(v)), 2),
            "up_pct": round(float((v > 0).mean() * 100), 0), "t": round(t, 2) if t is not None else None}


def seasonality(symbol: str) -> dict:
    sym = symbol.upper()
    close = data.store()["close"]
    if sym not in close.columns:
        raise not_found(f"Price history for {sym}")
    tab = _monthly(close[sym])
    if tab.empty or len(tab) < 3:
        raise ApiException("FEATURE_UNAVAILABLE", f"Too little history for {sym}'s seasonality.", None, {"feature": "seasonality"})
    nifty = _monthly(close[INDEX_NIFTY]) if INDEX_NIFTY in close.columns else pd.DataFrame()
    months = []
    for m in range(1, 13):
        st = _stats(tab[m]) if m in tab.columns else _stats(pd.Series(dtype=float))
        ex = None
        if not nifty.empty and m in tab.columns and m in nifty.columns:
            both = (tab[m] - nifty[m]).dropna()
            ex = _stats(both)
        months.append({"month": m, "name": MONTHS[m - 1], **st, "vs_nifty": ex,
                       "pattern": bool(st["t"] is not None and abs(st["t"]) >= 2 and st["n"] >= 8)})
    years = [{"year": int(y), "rets": [None if pd.isna(tab.at[y, m]) else round(float(tab.at[y, m]), 2) if m in tab.columns else None
                                       for m in range(1, 13)]} for y in tab.index]
    return {"symbol": sym, "first_year": int(tab.index[0]), "last_year": int(tab.index[-1]), "months": months,
            "years": years,
            "note": ("Average return of each calendar month over the years shown. About ten years per month is a small "
                     "sample: only a month with |t| of 2 or more (and 8+ years) is marked; the rest is noise. Not a "
                     "forecast.")}


def _quote_time(q: dict) -> str | None:
    """When a quote was taken: its fetch time (FYERS / Yahoo cache) or the live feed's tick time."""
    if q.get("fetched"):
        return str(q["fetched"])
    if q.get("source") == "live" and q.get("tick_at"):
        try:
            return datetime.fromtimestamp(float(q["tick_at"]), IST).isoformat(timespec="seconds")
        except (TypeError, ValueError, OverflowError, OSError):
            return None
    return None


def heatmap(period: str = "1d") -> dict:
    if period not in PERIODS:
        raise ApiException("VALIDATION", f"period must be one of {', '.join(PERIODS)}.")
    sc = data.screener()
    if sc is None or sc.empty:
        raise ApiException("FEATURE_UNAVAILABLE", "No scan results yet.", "Run a scan first.", {"feature": "heatmap"})
    col = PERIODS[period]
    rows = sc[["symbol", "company", "industry", "price", "turnover_cr", col]].rename(columns={col: "move"}).copy()
    rows["industry"] = rows["industry"].fillna("Other")
    rows = rows[rows["turnover_cr"].fillna(0) > 0]
    rows["source"] = "scan"
    session, live_n, refreshing, times = None, 0, False, []
    if period == "1d":
        try:     # never waits for the network: what is at hand now, the stale quotes fetched in the background
            q = quotes_svc.quotes(list(rows["symbol"]), allow_network=True, wait=False)
            session, refreshing = q.get("session"), bool(q.get("refreshing"))
            live = {x["symbol"]: x for x in q["quotes"] if x.get("source") in ("live", "fyers", "yahoo") and x.get("change_pct") is not None}
            if live:
                rows["move"] = [live[s]["change_pct"] if s in live else m for s, m in zip(rows["symbol"], rows["move"])]
                rows["price"] = [live[s]["price"] if s in live else p for s, p in zip(rows["symbol"], rows["price"])]
                rows["source"] = [live[s]["source"] if s in live else "scan" for s in rows["symbol"]]
                live_n = len(live)
                times = sorted(t for x in live.values() for t in [_quote_time(x)] if t)
        except Exception:
            log.exception("Heatmap quotes failed")   # the last scan's numbers then
    groups = []
    for ind, g in rows.groupby("industry"):
        size = float(g["turnover_cr"].sum())
        w = g["turnover_cr"].to_numpy(dtype=float)
        mv = g["move"].to_numpy(dtype=float)
        ok = ~np.isnan(mv)
        groups.append({"industry": ind, "size": round(size, 1),
                       "move": round(float(np.average(mv[ok], weights=w[ok])), 2) if ok.any() and w[ok].sum() > 0 else None,
                       "up": int((mv > 0).sum()), "down": int((mv < 0).sum()),
                       "stocks": [{"symbol": r.symbol, "company": r.company, "price": None if pd.isna(r.price) else round(float(r.price), 2),
                                   "size": round(float(r.turnover_cr), 1), "move": None if pd.isna(r.move) else round(float(r.move), 2),
                                   "source": r.source}
                                  for r in g.sort_values("turnover_cr", ascending=False).itertuples()]})
    groups.sort(key=lambda x: -x["size"])
    latest = data.latest() or {}
    return {"period": period, "groups": groups, "stocks": int(len(rows)), "live": live_n, "session": session,
            "as_of": now_ist().isoformat(timespec="seconds"),
            # where each move came from (live / fyers / yahoo / scan), how old the quotes are, and whether the
            # stale ones are being fetched right now (they show on the next load)
            "sources": dict(Counter(rows["source"])), "quotes_from": times[0] if times else None,
            "quotes_to": times[-1] if times else None, "refreshing": refreshing,
            "scan_date": latest.get("data_date"),
            "note": ("Box size: 20-day traded value (the closest free proxy for size; NSE's day files carry no market "
                     "cap). Colour: the move over the period" + (
                         " - from 09:15 to 18:00 the freshest price at hand (live feed, FYERS, else Yahoo ~15 min "
                         "late), else the last scan's." if period == "1d" else ".")),
            "as_of_scan": str(sc["scan_id"].iloc[0]) if "scan_id" in sc.columns and len(sc) else None}
