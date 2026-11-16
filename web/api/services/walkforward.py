"""Walk-forward check of the app's own selection rule: does following the "working" strategies pay?

The Action card and the strategy lists only act on strategies whose status is *working* (engine.working_status:
beat both the Nifty 50 and the average stock over the last 12 and 6 months, and no loss over the whole history).
This replays that rule month by month on the backtest curves (curves.parquet), using only the data up to each
month-end, and holds the strategies it would have called working - equal weight - for the next month. The result is
compared with holding every strategy, the average stock and the Nifty 50 over exactly the same months, with a
t-statistic on the monthly difference. Out of sample for the rule (the curves themselves are backtests with fixed,
untuned parameters). Past behaviour only.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import data
from ..caches import KeyedCache, file_key, register
from ..errors import ApiException
from ..paths import P

BENCH = ("NIFTY 50", "Average stock", "NIFTY 500")
_cache = register(KeyedCache(2))


def _r(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def replay(c: pd.DataFrame) -> dict:
    strat = [x for x in c.columns if x not in BENCH]
    nifty = c.get("NIFTY 50")
    ew = c.get("Average stock")
    month_ends = c.groupby(c.index.to_period("M")).tail(1).index
    rows, picks = [], []
    for k in range(len(month_ends) - 1):
        m, nxt = month_ends[k], month_ends[k + 1]
        i = c.index.get_loc(m)
        if i < 252:
            continue
        working = []
        for s in strat:
            eq = c[s]
            if not (np.isfinite(eq.iloc[i]) and np.isfinite(eq.iloc[i - 252]) and np.isfinite(eq.iloc[i - 126])):
                continue
            first = eq.iloc[:i + 1].dropna()
            if len(first) > 1 and first.iloc[-1] < first.iloc[0]:
                continue                                           # lost money over the history to date
            ok = True
            for n in (252, 126):
                r = eq.iloc[i] / eq.iloc[i - n] - 1
                refs = [b.iloc[i] / b.iloc[i - n] - 1 for b in (nifty, ew) if b is not None and np.isfinite(b.iloc[i - n])]
                if not refs or r <= max(refs):
                    ok = False
            if ok:
                working.append(s)
        nxt_ret = {s: c[s].loc[nxt] / c[s].loc[m] - 1 for s in strat if np.isfinite(c[s].loc[nxt]) and np.isfinite(c[s].loc[m])}
        all_ret = float(np.mean(list(nxt_ret.values()))) if nxt_ret else 0.0
        w_ret = float(np.mean([nxt_ret[s] for s in working if s in nxt_ret])) if any(s in nxt_ret for s in working) else None
        rows.append({"month": nxt, "working": w_ret, "all": all_ret,
                     "ew": (ew.loc[nxt] / ew.loc[m] - 1) if ew is not None else None,
                     "nifty": (nifty.loc[nxt] / nifty.loc[m] - 1) if nifty is not None else None, "n_working": len(working)})
        picks.append({"month": nxt.date().isoformat(), "working": working})
    df = pd.DataFrame(rows).set_index("month")
    # a month with no working strategy holds cash (0%): what following the rule would have done
    df["follow"] = df["working"].fillna(0.0)
    yrs = len(df) / 12

    def cagr(col):
        g = (1 + df[col].fillna(0)).prod()
        return _r((g ** (1 / yrs) - 1) * 100, 1) if yrs > 0 else None

    diff = df["follow"] - df["all"]
    t = diff.mean() / (diff.std(ddof=1) / math.sqrt(len(diff))) if len(diff) > 2 and diff.std(ddof=1) > 0 else None
    curves = {col: [_r(x, 4) for x in (1 + df[col].fillna(0)).cumprod()] for col in ("follow", "all", "ew", "nifty")}
    return {"from": df.index[0].date().isoformat(), "to": df.index[-1].date().isoformat(), "months": int(len(df)),
            "cagr_pct": {"follow": cagr("follow"), "all": cagr("all"), "ew": cagr("ew"), "nifty": cagr("nifty")},
            "beat_all_pct": _r((diff > 0).mean() * 100, 1), "t_vs_all": _r(t), "avg_working": _r(df["n_working"].mean(), 1),
            "cash_months": int(df["working"].isna().sum()),
            "curve": {"t": [d.date().isoformat() for d in df.index], **curves}, "recent_picks": picks[-6:][::-1],
            "verdict": ("pays" if t is not None and t >= 2 else "hurts" if t is not None and t <= -2 else "no_difference"),
            "note": NOTE}


NOTE = ("Each month-end the app's own rule (beat both the Nifty 50 and the average stock over the last 12 and 6 "
        "months, no loss to date) is applied with only the data up to then; the strategies it calls working are held, "
        "equal weight, for the next month (cash when none). Compared with holding every strategy, the average stock "
        "and the Nifty 50. Past behaviour only.")


def report() -> dict:
    c = data.curves()
    if c is None or c.empty:
        raise ApiException("FEATURE_UNAVAILABLE", "No backtest curves yet.", "Run a scan first.", {"feature": "curves"})
    return _cache.get(file_key(P.curves), lambda: replay(c))
