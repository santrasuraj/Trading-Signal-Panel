"""Seasonality across the market: which stocks and sectors have tended to rise or fall in each calendar month and each
Indian market season, how many such "patterns" chance alone would produce, and whether trading them has worked.

Returns are calendar-month returns from month-end closes (a season compounds its months; the month in progress is left
out until it ends), measured against the NIFTY 500 index so a strong market month does not make every stock look
seasonal. For each stock and period: the years it was in the data, its average and median return over the index, the
share of years it beat the index, and a t-statistic.

About eight years per month is a small sample, and ~500 stocks x 12 months is a lot of tries: some stocks will look
consistent by luck. Two checks keep the page honest:

  chance      the month labels inside each year are shuffled (the same shuffle for every stock and the index, so the
              market's moves and sectors stay intact) and the stocks that still pass are counted: that is how many
              "consistent" stocks noise alone gives. A list is only interesting when it clearly beats that count.
  walk-fwd    for every month (or season) from the fifth year of data on, the 10 stocks with the best record in that
              period over the EARLIER years only are bought at the period's start and sold at its end, from the
              point-in-time top 500 (stocks that later collapsed or were delisted included), after round-trip costs.
              Their return over the index is the test; the 10 worst-record stocks are tracked the same way.

Descriptive base rates, not a forecast.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December")
# Indian market seasons: every month in exactly one, each inside one calendar year
SEASONS = (
    {"key": "budget", "name": "Budget season", "months": (1, 2), "why": "Q3 results and the Union Budget on 1 February"},
    {"key": "fy_end", "name": "Financial year-end", "months": (3,),
     "why": "advance tax, tax-loss selling and funds' year-end positioning"},
    {"key": "summer", "name": "Summer and Q4 results", "months": (4, 5),
     "why": "the new financial year and full-year results"},
    {"key": "monsoon", "name": "Monsoon", "months": (6, 7, 8, 9), "why": "rainfall, rural demand and Q1 results"},
    {"key": "festive", "name": "Festive season and Q2 results", "months": (10, 11),
     "why": "Navratri-to-Diwali spending and Q2 results"},
    {"key": "year_end", "name": "Year-end", "months": (12,), "why": "foreign funds' year-end and holiday trading"},
)
MIN_YEARS = 6                 # a stock needs this many years of the period to be listed
CONSISTENT_T, CONSISTENT_RATE = 2.0, 75.0     # |t| and the share of years beating (or lagging) the index
LEAN_T, LEAN_RATE = 1.5, 70.0
TOP_N = 10                    # walk-forward: stocks bought (and tracked at the bottom)
TRAIN_MIN_YEARS = 4           # ... each with at least this many earlier years of the period
PERMUTATIONS = 200          # 30 left the 95th percentile of the chance count swinging by +-5 stocks
SEED = 7


def period_list() -> list[dict]:
    """Every period the page offers: 12 months, then the seasons."""
    out = [{"key": str(m), "kind": "month", "name": MONTH_NAMES[m - 1], "short": MONTHS[m - 1], "months": (m,),
            "why": None} for m in range(1, 13)]
    out += [{"key": s["key"], "kind": "season", "name": s["name"],
             "short": f"{MONTHS[s['months'][0] - 1]}-{MONTHS[s['months'][-1] - 1]}" if len(s["months"]) > 1
             else MONTHS[s["months"][0] - 1], "months": s["months"], "why": s["why"]} for s in SEASONS]
    return out


def find_period(key: str) -> dict | None:
    return next((p for p in period_list() if p["key"] == str(key)), None)


def season_of(month: int) -> dict:
    return next(p for p in period_list() if p["kind"] == "season" and month in p["months"])


# ------------------------------------------------------------------ returns
def month_end_closes(close: pd.DataFrame) -> pd.DataFrame:
    """Each month's last close per symbol (the last traded one, so a stock delisted mid-month keeps its final price);
    the month in progress is dropped until it ends."""
    if close.empty:
        return close
    me = close.groupby(close.index.to_period("M")).last()
    last = close.index[-1]
    if me.index[-1] == last.to_period("M") and last.month == (last + pd.offsets.BDay(1)).month:
        me = me.iloc[:-1]
    return me


def monthly_returns(close: pd.DataFrame) -> pd.DataFrame:
    """Calendar-month returns (%) per symbol, indexed by month (PeriodIndex); NaN where a month-end close is missing."""
    me = month_end_closes(close)
    return (me / me.shift(1) - 1) * 100


DISAGREE_PTS = 2.0          # a stock-month whose two adjusted histories differ by more is left out


def drop_disagreements(a: pd.DataFrame, b: pd.DataFrame, tol: float = DISAGREE_PTS
                       ) -> tuple[pd.DataFrame, pd.DataFrame, list[tuple[str, pd.Period, float, float]]]:
    """Monthly returns from two independently adjusted price histories (the price store and the point-in-time NSE
    files): where both have a month and they differ by more than `tol` points - in practice the months of a demerger or
    rights issue, which each history adjusts differently - neither can be trusted, so the month is set to NaN
    in both. Returns (a, b, [(symbol, month, a_value, b_value), ...])."""
    cols = a.columns.intersection(b.columns)
    rows = a.index.intersection(b.index)
    if not len(cols) or not len(rows):
        return a, b, []
    x, y = a.loc[rows, cols], b.loc[rows, cols]
    bad = (x - y).abs().gt(tol) & x.notna() & y.notna()
    cells = [(c, r, float(x.at[r, c]), float(y.at[r, c])) for r, c in bad.stack().loc[lambda v: v].index]
    if cells:
        a, b = a.copy(), b.copy()
        for c, r, _va, _vb in cells:
            a.at[r, c] = np.nan
            b.at[r, c] = np.nan
    return a, b, cells


def period_returns(mret: pd.DataFrame, months: tuple[int, ...]) -> pd.DataFrame:
    """Years x symbols: the period's return (%) each year, compounding its months; NaN unless every month is there."""
    if mret.empty:
        return pd.DataFrame()
    parts = []
    for m in months:
        x = mret[mret.index.month == m]
        x.index = x.index.year
        parts.append(x)
    years = sorted(set().union(*[set(p.index) for p in parts]))
    g = pd.DataFrame(1.0, index=years, columns=mret.columns)
    for p in parts:
        g = g * (1 + p.reindex(years) / 100)              # NaN anywhere -> NaN: a partial period is no period
    return (g - 1) * 100


# ------------------------------------------------------------------ statistics
def _t(v: np.ndarray) -> float | None:
    v = v[np.isfinite(v)]
    n = len(v)
    if n < 3:
        return None
    sd = v.std(ddof=1)
    return float(v.mean() / (sd / math.sqrt(n))) if sd > 0 else None


def strength(n: int, t: float | None, beat_pct: float | None, side: int) -> str:
    """consistent / lean / noise for a bullish (side +1) or bearish (side -1) record."""
    if n < MIN_YEARS or t is None or beat_pct is None:
        return "noise"
    rate = beat_pct if side > 0 else 100 - beat_pct
    if side * t >= CONSISTENT_T and rate >= CONSISTENT_RATE:
        return "consistent"
    if side * t >= LEAN_T or rate >= LEAN_RATE:
        return "lean"
    return "noise"


def stock_stats(per: pd.DataFrame, bench: pd.Series) -> pd.DataFrame:
    """One row per symbol: years, average and median return, average excess over the bench, the share of years up and
    beating the bench, the t-statistic of the excess, its strength, and each year's excess."""
    ex = per.sub(bench.reindex(per.index), axis=0)
    rows = []
    for sym in per.columns:
        e, r = ex[sym].dropna(), per[sym].dropna()
        n = len(e)
        if n == 0:
            continue
        t = _t(e.to_numpy(float))
        beat = float((e > 0).mean() * 100)
        side = 1 if e.mean() > 0 else -1
        rows.append({"symbol": sym, "n": n, "beat_years": int((e > 0).sum()), "lag_years": int((e < 0).sum()),
                     "avg_pct": float(r.mean()), "median_pct": float(r.median()),
                     "up_pct": float((r > 0).mean() * 100), "excess_pct": float(e.mean()),
                     "median_excess_pct": float(e.median()), "beat_pct": beat, "t": t,
                     "strength": strength(n, t, beat, side), "years": {int(y): float(v) for y, v in e.items()}})
    return pd.DataFrame(rows)


def bench_stats(bench_per: pd.Series) -> dict:
    v = bench_per.dropna()
    t = _t(v.to_numpy(float))
    return {"n": int(len(v)), "avg_pct": _r(v.mean()) if len(v) else None, "median_pct": _r(v.median()) if len(v) else None,
            "up_pct": _r((v > 0).mean() * 100, 0) if len(v) else None, "t": _r(t),
            "years": {int(y): _r(x) for y, x in v.items()}}


def sector_grid(mret: pd.DataFrame, bench: str, industry: dict[str, str], min_stocks: int = 5) -> list[dict]:
    """Every sector against every period: the equal-weight average excess of its stocks each year, then the average
    over the years, its t and the share of years it beat the index."""
    by: dict[str, list[str]] = {}
    for s in mret.columns:
        ind = industry.get(s)
        if ind and s != bench:
            by.setdefault(ind, []).append(s)
    sectors = {k: v for k, v in sorted(by.items()) if len(v) >= min_stocks}
    if not sectors or bench not in mret.columns:
        return []
    cols = [c for v in sectors.values() for c in v]
    cells: dict[str, list[dict]] = {k: [] for k in sectors}
    for p in period_list():
        per = period_returns(mret[cols + [bench]], p["months"])
        ex = per[cols].sub(per[bench], axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for ind, syms in sectors.items():
                e = ex[syms].mean(axis=1, skipna=True).dropna()
                t = _t(e.to_numpy(float))
                cells[ind].append({"period": p["key"], "n": int(len(e)), "excess_pct": _r(e.mean()) if len(e) else None,
                                   "beat_pct": _r((e > 0).mean() * 100, 0) if len(e) else None, "t": _r(t)})
    return [{"industry": ind, "stocks": len(syms), "cells": cells[ind]} for ind, syms in sectors.items()]


# ------------------------------------------------------------------ chance: how many "consistent" stocks noise gives
def _count_consistent(e: np.ndarray) -> tuple[int, int]:
    """Consistent bullish / bearish counts from a years x stocks array of excess returns (NaN = no year)."""
    ok = np.isfinite(e)
    n = ok.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        x = np.where(ok, e, np.nan)
        mean = np.nanmean(x, axis=0)
        sd = np.nanstd(x, axis=0, ddof=1)
        t = mean / (sd / np.sqrt(n))
        beat = np.where(ok, e > 0, False).sum(axis=0) / np.maximum(n, 1) * 100
    good = (n >= MIN_YEARS) & np.isfinite(t)
    bull = good & (t >= CONSISTENT_T) & (beat >= CONSISTENT_RATE)
    bear = good & (-t >= CONSISTENT_T) & (100 - beat >= CONSISTENT_RATE)
    return int(bull.sum()), int(bear.sum())


def consistent_counts(mret: pd.DataFrame, bench: str, months: tuple[int, ...]) -> tuple[int, int]:
    """How many stocks pass as consistent bullish and bearish."""
    per = period_returns(mret, months)
    if per.empty:
        return 0, 0
    return _count_consistent(per.drop(columns=[bench]).sub(per[bench], axis=0).to_numpy(float))


def shuffle_months(mret: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """The month labels shuffled within each calendar year - the same shuffle for every column, so the market's moves
    and sectors stay together; a partial first or last year shuffles among the months it has."""
    parts = []
    for y in sorted(set(mret.index.year)):
        block = mret[mret.index.year == y]
        if len(block) < 2:
            parts.append(block)
            continue
        shuffled = block.iloc[rng.permutation(len(block))].copy()
        shuffled.index = block.index                      # month m now holds another month's returns
        parts.append(shuffled)
    return pd.concat(parts)


def chance_counts(mret: pd.DataFrame, bench: str, months: tuple[int, ...], n_perm: int = PERMUTATIONS,
                  seed: int = SEED) -> dict:
    """Average consistent bullish / bearish counts over `n_perm` shuffles of the month labels - exactly
    shuffle_months's shuffles (same random draws, same order), done on a years x 12 x stocks array for speed."""
    years = sorted(set(mret.index.year))
    yi = {y: k for k, y in enumerate(years)}
    R = np.full((len(years), 12, mret.shape[1]), np.nan)
    present = np.zeros((len(years), 12), dtype=bool)
    vals = mret.to_numpy(float)
    for k, per in enumerate(mret.index):
        R[yi[per.year], per.month - 1] = vals[k]
        present[yi[per.year], per.month - 1] = True
    slots = [np.flatnonzero(present[k]) for k in range(len(years))]
    b = mret.columns.get_loc(bench)
    stocks = np.array([c for c in range(mret.shape[1]) if c != b])
    rng = np.random.default_rng(seed)
    bull, bear = [], []
    for _ in range(n_perm):
        S = R.copy()
        for k, pos in enumerate(slots):
            if len(pos) >= 2:
                S[k, pos] = R[k, pos[rng.permutation(len(pos))]]
        g = np.ones((len(years), mret.shape[1]))
        for m in months:
            g = g * (1 + S[:, m - 1, :] / 100)            # NaN anywhere -> NaN: no period that year
        per = (g - 1) * 100
        x, y = _count_consistent(per[:, stocks] - per[:, [b]])
        bull.append(x)
        bear.append(y)
    return {"bullish": _r(float(np.mean(bull)), 1), "bearish": _r(float(np.mean(bear)), 1),
            "bullish_p95": int(np.percentile(bull, 95)), "bearish_p95": int(np.percentile(bear, 95)),
            "permutations": n_perm}


# ------------------------------------------------------------------ walk-forward test (point-in-time)
def walk_forward(mret: pd.DataFrame, member_start: pd.DataFrame, bench: str, months: tuple[int, ...],
                 cost_pct: float, top_n: int = TOP_N, train_min: int = TRAIN_MIN_YEARS) -> list[dict]:
    """Each year with enough history: rank the stocks in the universe at the period's start by their average excess
    in that period over the earlier years only, then record what the top and bottom `top_n` did in it (top after the
    round-trip `cost_pct`). `member_start`: months (PeriodIndex) x symbols, True when in the universe at the month's
    first trading day."""
    per = period_returns(mret, months)
    if per.empty or bench not in per.columns:
        return []
    ex = per.drop(columns=[bench]).sub(per[bench], axis=0)
    start_month = min(months)
    out = []
    for y in ex.index:
        past = ex.loc[ex.index < y]
        start = pd.Period(year=int(y), month=start_month, freq="M")
        if past.empty or start not in member_start.index:
            continue
        members = member_start.loc[start].reindex(ex.columns).fillna(False).astype(bool)
        now = ex.loc[y]
        ok = (past.notna().sum() >= train_min) & members & now.notna()
        if int(ok.sum()) < 2 * top_n:
            continue
        score = past.loc[:, ok].mean().sort_values(ascending=False, kind="mergesort")
        top, bottom = list(score.index[:top_n]), list(score.index[-top_n:])
        out.append({"year": int(y), "eligible": int(ok.sum()), "top": top, "bottom": bottom,
                    "top_excess_pct": _r(float(now[top].mean()) - cost_pct),
                    "bottom_excess_pct": _r(float(now[bottom].mean())),
                    "all_excess_pct": _r(float(now[ok].mean())), "bench_pct": _r(float(per.at[y, bench]))})
    return out


def summarize(results: list[dict]) -> dict:
    """The walk-forward record and its evidence label (the app's: working / mixed / not-working / untested)."""
    top = np.array([r["top_excess_pct"] for r in results if r.get("top_excess_pct") is not None], dtype=float)
    bot = np.array([r["bottom_excess_pct"] for r in results if r.get("bottom_excess_pct") is not None], dtype=float)
    if len(top) == 0:
        return {"n": 0, "status": "untested"}
    t_top, t_bot = _t(top), _t(bot)
    if len(top) < 12:
        status = "untested"
    elif top.mean() > 0 and (t_top or 0) >= 2:
        status = "working"
    elif top.mean() > 0:
        status = "mixed"
    else:
        status = "not-working"
    return {"n": int(len(top)), "status": status, "top_avg_pct": _r(top.mean()), "top_t": _r(t_top),
            "top_hit_pct": _r((top > 0).mean() * 100, 0), "top_total_pct": _r((np.prod(1 + top / 100) - 1) * 100),
            "bottom_avg_pct": _r(bot.mean()) if len(bot) else None, "bottom_t": _r(t_bot),
            "bottom_hit_pct": _r((bot < 0).mean() * 100, 0) if len(bot) else None,
            "first": results[0].get("label") or results[0].get("year"),
            "last": results[-1].get("label") or results[-1].get("year")}


def _r(x, nd=2):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), nd)
