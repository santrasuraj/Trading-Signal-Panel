"""Volatility (GET /api/volatility): how expensive options are now, against their own past and against how much the
index actually moved.

  * NIFTY: India VIX (NSE's 30-day implied volatility of NIFTY options) since 2018: today's level, its rank and
    percentile over the last year, the Nifty 50's realised volatility (20 days, annualised) and the expected move
    the VIX prices (1 day, 1 week, 1 month: VIX x sqrt(days / 252), about one standard deviation).
  * BANKNIFTY (and NIFTY as a cross-check): the at-the-money implied volatility of the nearest expiry with 7+ days
    left, each day, from NSE's daily option prices (scanner/option_history.py; as far back as that store goes).
  * The record (NIFTY, since 2018): the VIX against the volatility that followed over the next 21 trading days, by
    VIX percentile: option sellers earn this gap on average (the variance risk premium) and lose it in the worst
    months; both are shown.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from scanner import option_history as oh, options as opt

from . import data

YEAR = 252


def _rv(close: pd.Series, n: int = 20) -> pd.Series:
    r = np.log(close / close.shift(1))
    return r.rolling(n, min_periods=n).std() * math.sqrt(YEAR) * 100


def _rank(s: pd.Series, now: float) -> tuple[float | None, float | None]:
    s = s.dropna()
    if len(s) < 20:
        return None, None
    lo, hi = float(s.min()), float(s.max())
    rank = (now - lo) / (hi - lo) * 100 if hi > lo else None
    pctl = float((s < now).mean() * 100)
    return (round(rank, 1) if rank is not None else None), round(pctl, 1)


def atm_iv_series(symbol: str) -> pd.Series:
    """Daily ATM implied volatility (%) of the nearest expiry with 7+ days left, from the stored daily option prices."""
    h = oh.load(symbol)
    if h.empty:
        return pd.Series(dtype=float)
    h = h[(h["expiry"] - h["date"]).dt.days >= 7]
    h = h[h["expiry"] == h.groupby("date")["expiry"].transform("min")]
    wide = h.pivot_table(index=["date", "strike"], columns="type", values="close", aggfunc="first")
    if not {"CE", "PE"} <= set(wide.columns):
        return pd.Series(dtype=float)
    wide = wide[(wide["CE"] > 0) & (wide["PE"] > 0)].reset_index()
    spot = h.groupby("date")["underlying"].first()
    expiry = h.groupby("date")["expiry"].first()
    wide["dist"] = (wide["strike"] - wide["date"].map(spot)).abs()
    atm = wide.loc[wide.groupby("date")["dist"].idxmin()]
    r = 0.065
    atm = atm.assign(days=[max((expiry[d] - d).days, 1) for d in atm["date"]])
    out = {}
    for days, g in atm.groupby("days"):                  # one vectorised solve per time to expiry
        T = days / 365
        k = g["strike"].to_numpy(float)
        F = k + (g["CE"].to_numpy(float) - g["PE"].to_numpy(float)) * math.exp(r * T)   # put-call parity at the ATM strike
        n = len(g)
        ivs = opt.implied_vol(np.r_[g["CE"].to_numpy(float), g["PE"].to_numpy(float)], np.r_[F, F], np.r_[k, k], T, r,
                              np.r_[np.ones(n), np.zeros(n)])
        both = np.vstack([ivs[:n], ivs[n:]])
        with np.errstate(all="ignore"):
            iv = np.nanmean(both, axis=0)
        for d, v in zip(g["date"], iv):
            if v == v:
                out[d] = round(float(v) * 100, 2)
    return pd.Series(out).sort_index()


def record(vix: pd.Series, close: pd.Series) -> dict:
    """VIX against the realised volatility of the next 21 trading days, overall and by VIX percentile (1-year)."""
    fut = _rv(close, 21).shift(-21)
    df = pd.DataFrame({"vix": vix, "fut": fut}).dropna()
    if len(df) < 100:
        return {}
    df["gap"] = df["vix"] - df["fut"]
    v = vix.to_numpy(float)
    pc = np.full(len(v), np.nan)
    if len(v) > YEAR:                                     # the share of the previous year's days below each day
        w = np.lib.stride_tricks.sliding_window_view(v, YEAR + 1)
        pc[YEAR:] = (w[:, :-1] < w[:, -1:]).mean(axis=1) * 100
    pctl = pd.Series(pc, index=vix.index).reindex(df.index)
    df["bucket"] = pd.cut(pctl, [0, 25, 50, 75, 100], labels=["0-25", "25-50", "50-75", "75-100"], include_lowest=True)
    by = []
    for b, g in df.dropna(subset=["bucket"]).groupby("bucket", observed=True):
        by.append({"bucket": str(b), "days": int(len(g)), "vix_avg": round(float(g["vix"].mean()), 1),
                   "then_avg": round(float(g["fut"].mean()), 1), "gap_avg": round(float(g["gap"].mean()), 1),
                   "gap_worst": round(float(g["gap"].min()), 1),
                   "below_pct": round(float((g["fut"] < g["vix"]).mean() * 100), 1)})
    return {"days": int(len(df)), "gap_avg": round(float(df["gap"].mean()), 1),
            "below_pct": round(float((df["fut"] < df["vix"]).mean() * 100), 1),
            "gap_worst": round(float(df["gap"].min()), 1), "by_percentile": by}


_cache: dict = {}


def view() -> dict:
    ih = data.index_history()
    p = oh.path()
    key = (len(ih), str(ih.index[-1]) if len(ih) else None, p.stat().st_mtime_ns if p.exists() else None)
    if _cache.get("key") == key:
        return _cache["out"]
    out = _build(ih)
    _cache.update(key=key, out=out)
    return out


def _build(ih: pd.DataFrame) -> dict:
    vix = ih["India VIX"].dropna() if "India VIX" in ih.columns else pd.Series(dtype=float)
    nifty = ih["Nifty 50"].dropna() if "Nifty 50" in ih.columns else pd.Series(dtype=float)
    out: dict = {"as_of": vix.index[-1].date().isoformat() if len(vix) else None}
    if len(vix) and len(nifty):
        now = float(vix.iloc[-1])
        last_year = vix.iloc[-YEAR:]
        rank, pctl = _rank(last_year, now)
        rv = _rv(nifty)
        out["nifty"] = {
            "vix": round(now, 2), "vix_chg": round(float(vix.iloc[-1] - vix.iloc[-2]), 2) if len(vix) > 1 else None,
            "rank": rank, "percentile": pctl, "low_1y": round(float(last_year.min()), 2), "high_1y": round(float(last_year.max()), 2),
            "rv20": round(float(rv.iloc[-1]), 2) if rv.notna().any() else None,
            "spot": round(float(nifty.iloc[-1]), 2),
            "moves": {k: round(float(nifty.iloc[-1]) * now / 100 * math.sqrt(n / YEAR), 0) for k, n in (("day", 1), ("week", 5), ("month", 21))},
            "series": [{"t": t.date().isoformat(), "vix": round(float(v), 2), "rv": (round(float(rv.get(t)), 2) if pd.notna(rv.get(t)) else None)}
                       for t, v in vix.iloc[-YEAR * 2:].items()],
            "record": record(vix, nifty),
        }
    ivs = {}
    for sym, idx_name in (("BANKNIFTY", "Nifty Bank"), ("NIFTY", "Nifty 50")):
        s = atm_iv_series(sym)
        if s.empty:
            continue
        under = ih[idx_name].dropna() if idx_name in ih.columns else pd.Series(dtype=float)
        rv = _rv(under)
        now = float(s.iloc[-1])
        rank, pctl = _rank(s, now)
        ivs[sym] = {"iv": now, "rank": rank, "percentile": pctl, "days": int(len(s)), "first": s.index[0].date().isoformat(),
                    "rv20": round(float(rv.iloc[-1]), 2) if len(rv) and rv.notna().any() else None,
                    "series": [{"t": t.date().isoformat(), "iv": v, "rv": (round(float(rv.get(t)), 2) if pd.notna(rv.get(t)) else None)}
                               for t, v in s.items()]}
    out["atm_iv"] = ivs
    out["note"] = ("Rank: where today sits between the period's low (0) and high (100); percentile: the share of days "
                   "below today. Expected moves are one standard deviation: about 2 days in 3 stay inside.")
    return out
