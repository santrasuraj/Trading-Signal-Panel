"""Direction for an index's options, measured on the index itself.

The options verdict (scanner/option_verdict.py) needs a tested direction. For a stock it uses the outlook study of
similar setups across the top 500; an index is not a stock (it moves less, mean-reverts differently), so for NIFTY
and BANKNIFTY this study looks at the index's own history instead: every past day with today's setup - trend (close
vs its 50- and 200-day averages) and RSI 14 (below 40, 40-60, above 60) - and what the index did over the next 5, 10
and 20 trading days, compared with its average move over all days. The t-statistic is on monthly averages (the
windows of neighbouring days overlap). Only a setup beyond luck (|t| >= 2) gives the verdict a direction; most don't.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

HORIZONS = (5, 10, 20)
MIN_CASES = 60


def _rsi(c: pd.Series, n: int = 14) -> pd.Series:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def setups(close: pd.Series) -> pd.Series:
    """A code per day: 'up/up/mid' = above SMA200 / above SMA50 / RSI 40-60 (NaN until the averages exist)."""
    c = close.dropna()
    s200, s50, r = c.rolling(200, min_periods=200).mean(), c.rolling(50, min_periods=50).mean(), _rsi(c)
    ok = s200.notna() & s50.notna() & r.notna()
    code = (np.where(c > s200, "above200", "below200").astype(object) + "/"
            + np.where(c > s50, "above50", "below50").astype(object) + "/"
            + np.where(r < 40, "rsi<40", np.where(r > 60, "rsi>60", "rsi40-60")).astype(object))
    return pd.Series(code, index=c.index).where(ok)


DESCRIBE = {"above200": "above its 200-day average", "below200": "below its 200-day average",
            "above50": "above its 50-day", "below50": "below its 50-day",
            "rsi<40": "RSI under 40", "rsi>60": "RSI over 60", "rsi40-60": "RSI 40-60"}


def describe(code: str) -> str:
    return ", ".join(DESCRIBE.get(p, p) for p in code.split("/"))


def _r(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def match_for(close: pd.Series, name: str = "the index") -> dict | None:
    """Option-verdict compatible: {'stats': {'5': {excess_pct, median_pct, t, n, up_pct}, ...}, 'n', 'setup', ...}.
    excess = the setup's average forward move minus the index's average forward move over all days."""
    c = close.dropna()
    if len(c) < 400:
        return None
    code = setups(c)
    today = code.iloc[-1]
    if not isinstance(today, str):
        return None
    hit = (code == today).to_numpy()
    month = c.index.to_period("M")
    stats = {}
    for h in HORIZONS:
        fwd = (c.shift(-h) / c - 1) * 100
        valid = fwd.notna().to_numpy()
        base = fwd[valid].mean()
        x = fwd[hit & valid]
        if len(x) < MIN_CASES:
            stats[str(h)] = {"n": int(len(x)), "excess_pct": None, "median_pct": _r(x.median()) if len(x) else None, "t": None, "up_pct": None}
            continue
        ex = x - base
        monthly = ex.groupby(month[hit & valid]).mean()
        t = monthly.mean() / (monthly.std(ddof=1) / math.sqrt(len(monthly))) if len(monthly) > 2 and monthly.std(ddof=1) > 0 else None
        stats[str(h)] = {"n": int(len(x)), "excess_pct": _r(ex.mean()), "median_pct": _r(x.median()), "t": _r(t),
                         "up_pct": _r((x > 0).mean() * 100, 1)}
    return {"stats": stats, "n": int(hit.sum()), "setup": today, "setup_text": describe(today), "benchmark": f"{name}'s average move",
            "source": "index", "first_day": c.index[0].date().isoformat(), "last_day": c.index[-1].date().isoformat()}
