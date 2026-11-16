"""Do the option-chain readings predict anything? Measured on this app's own stored chains (data/options/), never
assumed. Three popular claims, each with its sample size:

  max pain       "price is pulled towards max pain by expiry": on each day, was the expiry close nearer to that
                 day's max pain than the spot was? A coin flip gives about 50%.
  expected move  the at-the-money straddle prices the size of the move to expiry: how often did the expiry close
                 land inside spot ± straddle? For a fair price about 57% (the mean absolute move of a normal
                 distribution covers 57.5% of outcomes); far more = options were dear, far less = cheap.
  put-call ratio "a high PCR is bullish" (or bearish, depending who you ask): the next day's move after the days with
                 the highest third of PCR minus after the lowest third, and their rank correlation.

Each claim says "not enough data" until MIN_DAYS end-of-day chains exist - about three months of the 09:12 task.
Nothing here becomes a signal unless a claim holds on enough days (Phase 5: signals only where there is proof).
"""
from __future__ import annotations

from datetime import date, time as dtime

import numpy as np
import pandas as pd

from . import options as opt

MIN_DAYS = 60
STRADDLE_FAIR_PCT = 57.5
EOD = dtime(15, 31)


def end_of_day(summaries: pd.DataFrame) -> pd.DataFrame:
    """One row per (day, symbol): the last chain stored by 15:31 for the nearest expiry not yet passed."""
    if summaries.empty:
        return summaries
    s = summaries.copy()
    s["time"] = pd.to_datetime(s["time"])
    s["day"] = s["time"].dt.date
    s["expiry_d"] = pd.to_datetime(s["expiry"]).dt.date
    s = s[(s["time"].dt.time <= EOD) & (s["expiry_d"] >= s["day"])]
    s = s.sort_values("time").groupby(["day", "symbol", "expiry_d"]).tail(1)
    nearest = s.groupby(["day", "symbol"])["expiry_d"].transform("min")
    return s[s["expiry_d"] == nearest].sort_values(["symbol", "day"]).reset_index(drop=True)


def load_summaries() -> pd.DataFrame:
    parts = [pd.read_parquet(p) for p in sorted(opt.folder().glob("[0-9]" * 8 + "/" + opt.SUMMARY_NAME))]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=opt.SUMMARY_COLS)


def _expiry_close(eod: pd.DataFrame) -> dict[tuple[str, date], float]:
    """(symbol, expiry) -> the spot at that expiry's close (its own last stored chain on the expiry day)."""
    on_day = eod[eod["day"] == eod["expiry_d"]]
    return {(r.symbol, r.expiry_d): float(r.spot) for r in on_day.itertuples(index=False)}


def _rank_corr(a: pd.Series, b: pd.Series) -> float | None:
    if len(a) < 3:
        return None
    r = np.corrcoef(a.rank(), b.rank())[0, 1]
    return float(r) if np.isfinite(r) else None


def study(eod: pd.DataFrame, symbol: str, min_days: int = MIN_DAYS) -> dict:
    """The three claims for one symbol."""
    e = eod[eod["symbol"] == symbol].sort_values("day").reset_index(drop=True)
    closes = _expiry_close(e)
    before = e[e["day"] < e["expiry_d"]].copy()
    before["exp_close"] = [closes.get((symbol, x)) for x in before["expiry_d"]]
    done = before.dropna(subset=["exp_close", "spot", "max_pain"])

    # max pain: was the expiry close nearer to max pain than the spot that day?
    gap_then = (done["spot"] - done["max_pain"]).abs()
    gap_end = (done["exp_close"] - done["max_pain"]).abs()
    mp = done[gap_then > 0]
    mp_hit = float((gap_end[mp.index] < gap_then[mp.index]).mean() * 100) if len(mp) else None

    # expected move: did the expiry close land inside spot +- straddle?
    em = done.dropna(subset=["straddle"])
    em_hit = (float(((em["exp_close"] - em["spot"]).abs() <= em["straddle"]).mean() * 100) if len(em) else None)

    # put-call ratio: the next stored day's move after the top vs bottom third of PCR
    e["next_ret"] = e["spot"].shift(-1) / e["spot"] - 1
    p = e.dropna(subset=["pcr_oi", "next_ret"])
    pcr = {"n": len(p), "corr": None, "top_minus_bottom_pct": None}
    if len(p) >= 9:
        lo, hi = p["pcr_oi"].quantile([1 / 3, 2 / 3])
        top, bot = p.loc[p["pcr_oi"] >= hi, "next_ret"], p.loc[p["pcr_oi"] <= lo, "next_ret"]
        pcr = {"n": len(p), "corr": _rank_corr(p["pcr_oi"], p["next_ret"]),
               "top_minus_bottom_pct": float((top.mean() - bot.mean()) * 100) if len(top) and len(bot) else None}

    def verdict(n: int, text: str) -> str:
        return text if n >= min_days else f"Not enough data yet: {n} of {min_days} days."

    return {
        "symbol": symbol, "days": int(e["day"].nunique()), "first_day": str(e["day"].min()) if len(e) else None,
        "max_pain": {"n": len(mp), "hit_pct": mp_hit, "fair_pct": 50.0,
                     "verdict": verdict(len(mp), "Pulled towards max pain more often than a coin flip."
                                         if mp_hit is not None and mp_hit > 55 else
                                         "No pull towards max pain beyond a coin flip.")},
        "expected_move": {"n": len(em), "inside_pct": em_hit, "fair_pct": STRADDLE_FAIR_PCT,
                          "verdict": verdict(len(em), "Options priced the move about right." if em_hit is not None
                                             and abs(em_hit - STRADDLE_FAIR_PCT) <= 8 else
                                             "Options overpriced the move (expiry closes mostly inside)."
                                             if em_hit is not None and em_hit > STRADDLE_FAIR_PCT else
                                             "Options underpriced the move (expiry closes often outside).")},
        "pcr": {**pcr, "verdict": verdict(pcr["n"], "PCR told nothing about the next day."
                                         if pcr["corr"] is None or abs(pcr["corr"]) < 0.15 else
                                         f"Some link between PCR and the next day (rank correlation {pcr['corr']:.2f}); "
                                         "check it holds before relying on it.")},
    }


def report(symbols: list[str] | None = None, min_days: int = MIN_DAYS) -> dict:
    eod = end_of_day(load_summaries())
    syms = symbols or (sorted(eod["symbol"].unique()) if len(eod) else [])
    return {"min_days": min_days, "studies": [study(eod, s, min_days) for s in syms]}
