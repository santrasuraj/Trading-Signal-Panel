"""How much of a strategy's backtest could be luck (GET /api/strategies/{key}/robustness).

  Monte Carlo   10,000 alternative histories: the strategy's own daily returns re-drawn in 21-day blocks (keeping
                runs of good and bad days together), each as long as the backtest. Gives the spread of yearly returns
                and worst drawdowns the same daily behaviour could have produced, and how often it would have lost
                money or trailed the average stock.
  Deflated      the Sharpe ratio corrected for how many strategies were tried (Bailey & Lopez de Prado, 2014): with
  Sharpe        ~20 strategies tested, the best one looks good by chance alone. 95%+ = unlikely to be luck.
  Consistency   every rolling 12-month window (monthly steps): how often the strategy beat the average stock, its
                worst and best year; and the first half of the backtest against the second half (does the edge last?).

All on the backtest's daily equity curve (curves.parquet), after costs. Past behaviour only.
"""
from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

from . import data
from ..caches import KeyedCache, file_key, register
from ..errors import ApiException
from ..paths import P

PATHS, CHUNK, BLOCK = 10_000, 1_000, 21
BENCH = ("Average stock", "NIFTY 500", "NIFTY 50")
EULER = 0.5772156649
_cache = register(KeyedCache(32))


def _r(x, nd=2):
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def monte_carlo(r: np.ndarray, bench_cagr: float | None, paths: int = PATHS, block: int = BLOCK, seed: int = 7) -> dict:
    """Block bootstrap of daily returns `r` (fractions)."""
    t = len(r)
    if t < block * 4:
        return {}
    rng = np.random.default_rng(seed)
    lr = np.log1p(np.clip(r, -0.99, None))
    nb = math.ceil(t / block)
    cagr, dd = [], []
    for k in range(0, paths, CHUNK):
        n = min(CHUNK, paths - k)
        starts = rng.integers(0, t - block + 1, size=(n, nb))
        idx = (starts[:, :, None] + np.arange(block)).reshape(n, -1)[:, :t]
        path = np.cumsum(lr[idx], axis=1)
        cagr.append(np.expm1(path[:, -1] * 252 / t))
        peak = np.maximum.accumulate(np.concatenate([np.zeros((n, 1)), path], axis=1), axis=1)[:, 1:]
        dd.append(np.expm1(np.min(path - peak, axis=1)))
    cagr, dd = np.concatenate(cagr) * 100, np.concatenate(dd) * 100
    q = lambda a, p: _r(np.percentile(a, p), 1)  # noqa: E731
    return {"paths": int(paths), "block_days": block,
            "cagr_pct": {"p5": q(cagr, 5), "p25": q(cagr, 25), "p50": q(cagr, 50), "p75": q(cagr, 75), "p95": q(cagr, 95)},
            "max_dd_pct": {"p5": q(dd, 5), "p50": q(dd, 50), "p95": q(dd, 95)},
            "prob_loss_pct": _r((cagr < 0).mean() * 100, 1),
            "prob_beat_bench_pct": _r((cagr > bench_cagr * 100).mean() * 100, 1) if bench_cagr is not None else None}


def deflated_sharpe(r: np.ndarray, trial_srs: list[float]) -> dict:
    """Probability that the true Sharpe ratio is above what the best of N tried strategies shows by luck."""
    t = len(r)
    sd = r.std(ddof=1)
    if t < 60 or not sd > 0:
        return {}
    sr = r.mean() / sd
    z = (r - r.mean()) / sd
    g3, g4 = float(np.mean(z ** 3)), float(np.mean(z ** 4))
    n = max(len(trial_srs), 2)
    v = float(np.var(trial_srs, ddof=1)) if len(trial_srs) > 1 else 0.0
    nd = NormalDist()
    sr0 = math.sqrt(v) * ((1 - EULER) * nd.inv_cdf(1 - 1 / n) + EULER * nd.inv_cdf(1 - 1 / (n * math.e)))
    denom = 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2
    if denom <= 0:
        return {}
    dsr = nd.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(denom))
    psr = nd.cdf(sr * math.sqrt(t - 1) / math.sqrt(denom))          # vs a Sharpe of zero, one strategy only
    return {"sharpe_ann": _r(sr * math.sqrt(252)), "expected_max_sharpe_ann": _r(sr0 * math.sqrt(252)),
            "trials": n, "deflated_pct": _r(dsr * 100, 1), "probabilistic_pct": _r(psr * 100, 1),
            "skew": _r(g3), "kurtosis": _r(g4)}


def consistency(eq: pd.Series, bench: pd.Series | None) -> dict:
    ann = lambda s: (s.iloc[-1] / s.iloc[0]) ** (252 / max(len(s) - 1, 1)) - 1  # noqa: E731
    out: dict = {}
    if len(eq) > 300:
        wins, rets = [], []
        for i in range(252, len(eq), 21):
            sr = eq.iloc[i] / eq.iloc[i - 252] - 1
            rets.append(sr)
            if bench is not None:
                br = bench.iloc[i] / bench.iloc[i - 252] - 1
                wins.append(sr > br)
        out.update(windows=len(rets), worst_12m_pct=_r(min(rets) * 100, 1), best_12m_pct=_r(max(rets) * 100, 1),
                   beat_bench_pct=_r(np.mean(wins) * 100, 1) if wins else None)
    half = len(eq) // 2
    if half > 252:
        out.update(first_half_cagr_pct=_r(ann(eq.iloc[:half + 1]) * 100, 1), second_half_cagr_pct=_r(ann(eq.iloc[half:]) * 100, 1),
                   first_half_from=eq.index[0].date().isoformat(), split_at=eq.index[half].date().isoformat())
        if bench is not None:
            out.update(first_half_bench_pct=_r(ann(bench.iloc[:half + 1]) * 100, 1),
                       second_half_bench_pct=_r(ann(bench.iloc[half:]) * 100, 1))
    return out


def report(key: str) -> dict:
    c = data.curves()
    if c is None or key not in c.columns:
        raise ApiException("NOT_FOUND", f"No backtest curve for {key}.", "Run a scan first.")

    def compute() -> dict:
        bench_name = next((b for b in BENCH if b in c.columns), None)
        eq = c[key].dropna()
        eq = eq[eq > 0]
        r = eq.pct_change().dropna().to_numpy()
        bench = c[bench_name].reindex(eq.index).ffill() if bench_name else None
        bench_cagr = None
        if bench is not None and bench.notna().sum() > 2:
            b = bench.dropna()
            bench_cagr = (b.iloc[-1] / b.iloc[0]) ** (252 / max(len(b) - 1, 1)) - 1
        strat_cols = [x for x in c.columns if x not in BENCH]
        srs = []
        for col in strat_cols:
            rr = c[col].dropna().pct_change().dropna().to_numpy()
            if len(rr) > 60 and rr.std(ddof=1) > 0:
                srs.append(rr.mean() / rr.std(ddof=1))
        actual = (eq.iloc[-1] / eq.iloc[0]) ** (252 / max(len(eq) - 1, 1)) - 1
        dd = float((eq / eq.cummax() - 1).min())
        mc = monte_carlo(r, bench_cagr)
        dsr = deflated_sharpe(r, srs)
        verdict = ("likely_real" if (dsr.get("deflated_pct") or 0) >= 95 and (mc.get("prob_beat_bench_pct") or 0) >= 75
                   else "maybe_luck" if (dsr.get("deflated_pct") or 0) >= 50 else "likely_luck")
        return {"key": key, "from": eq.index[0].date().isoformat(), "to": eq.index[-1].date().isoformat(), "days": int(len(r)),
                "benchmark": bench_name, "actual": {"cagr_pct": _r(actual * 100, 1), "max_dd_pct": _r(dd * 100, 1),
                                                    "bench_cagr_pct": _r(bench_cagr * 100, 1) if bench_cagr is not None else None},
                "monte_carlo": mc, "deflated_sharpe": dsr, "consistency": consistency(eq, bench), "verdict": verdict,
                "note": NOTE}

    return _cache.get((key, file_key(P.curves)), compute)


NOTE = ("Monte Carlo re-draws the backtest's own daily returns in 21-day blocks 10,000 times; the deflated Sharpe "
        "corrects for every strategy tried here (the best of many looks good by chance). Likely real = deflated "
        "Sharpe 95%+ and 75%+ of the Monte Carlo histories beat the average stock. Past behaviour only.")
