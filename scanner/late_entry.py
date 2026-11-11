"""Late entry: does a strategy's edge survive if you join its trade days after its own buy?

A ranking strategy buys on its review day and then holds; on every other day the screen can only say "the model
holds it". This study answers whether buying such a stock late still paid: for every trade of the strategy's
survivorship-free backtest (trades.parquet), enter 0, 5, 10 or 21 trading days after the model's entry (at that
day's open, only if the model still held it then) and exit when the model exited (its exit day's open). Each late
trade is compared with the average point-in-time top-500 member over exactly the same days, ~0.45% round-trip costs
subtracted, with a t-statistic on monthly averages (scanner/pattern_study.py's test).

The Action card (web/api/services/action_svc.py) shows a model-held stock as BUY (late entry) only when the
strategy's backtest is working AND its late-entry test at the matching delay shows an edge after costs; otherwise
NO EDGE, as before.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import pattern_study as ps
from .settings import ist_now

LAGS = (0, 5, 10, 21)
CHUNK = 4000
NOTE = ("For every trade of the strategy's 8-year survivorship-free backtest: buy 0, 5, 10 or 21 trading days after "
        "the model did (only if it still held the stock), sell when it sold, compared with the average top-500 stock "
        "over the same days, ~0.45% costs subtracted. An edge needs t >= 2 and a positive excess after costs over 100+ "
        "late trades in 24+ months.")


def _events(trades: pd.DataFrame, o: pd.DataFrame, member: pd.DataFrame) -> pd.DataFrame:
    cal = o.index
    pos = {s: j for j, s in enumerate(o.columns)}
    t = trades[trades["symbol"].isin(pos)].copy()
    if t.empty:
        return pd.DataFrame(columns=["strategy", "lag", "date", "ret", "bench"])
    e = cal.searchsorted(pd.to_datetime(t["entry_date"]).to_numpy())
    x = cal.searchsorted(pd.to_datetime(t["exit_date"]).to_numpy())
    cols = t["symbol"].map(pos).to_numpy()
    O = o.to_numpy(dtype=float)
    M = member.reindex(index=cal, columns=o.columns, fill_value=False).to_numpy(dtype=bool)
    rows = []
    for lag in LAGS:
        i = e + lag
        ok = (i < x) & (x < len(cal)) & (i < len(cal))
        if not ok.any():
            continue
        ii, xx, cc, ss = i[ok], x[ok], cols[ok], t["strategy"].to_numpy()[ok]
        ret = O[xx, cc] / O[ii, cc] - 1
        bench = np.full(len(ii), np.nan)
        for k in range(0, len(ii), CHUNK):
            a, b = ii[k:k + CHUNK], xx[k:k + CHUNK]
            r = O[b] / O[a] - 1                                     # every stock, same days
            m = M[np.maximum(a - 1, 0)] & np.isfinite(r)            # members the day before the late entry
            bench[k:k + CHUNK] = np.where(m.any(axis=1), np.nansum(np.where(m, r, 0.0), axis=1) / np.maximum(m.sum(axis=1), 1), np.nan)
        rows.append(pd.DataFrame({"strategy": ss, "lag": lag, "date": cal[ii], "ret": ret, "bench": bench}))
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=["strategy", "lag", "date", "ret", "bench"])


def study(trades: pd.DataFrame, opens: pd.DataFrame, member: pd.DataFrame) -> dict:
    ev = _events(trades, opens, member)
    out: dict = {}
    for (strat, lag), g in ev.groupby(["strategy", "lag"]):
        g = g.dropna(subset=["ret", "bench"])
        x = pd.DataFrame({"date": g["date"], "side": 1, f"excess_{lag}": g["ret"] - g["bench"]})
        s = ps.stats(x, lag)
        s["return_pct"] = None if g.empty else round(float(g["ret"].mean() * 100), 2)
        s["verdict"] = ps.verdict(s, True)
        out.setdefault(str(strat), {"trades": int((trades["strategy"] == strat).sum()), "lags": {}})["lags"][str(lag)] = s
    return {"generated_at": ist_now().isoformat(timespec="seconds"), "lags": list(LAGS), "cost_pct": ps.COST_PCT,
            "strategies": out, "note": NOTE}


def lag_for(days_held: int) -> int | None:
    """The tested delay that covers joining `days_held` trading days after the model's entry (None: too late)."""
    for lag in LAGS[1:]:
        if days_held <= lag:
            return lag
    return None
